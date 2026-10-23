"""``hermes reel plan --dry-run``: the plugin's only surface (round 5, R4-F4).

A CLI command and nothing else - no hooks, no slash commands, no tools, no schedule. It
runs the existing pipeline with the writer, title and entailment calls on ``ctx.llm``
(the production path), while redaction stays on the local route so only post-gate text is
ever sent to the host model.

``--dry-run`` is required on purpose: this is a planning command that writes its artefacts
to a directory the operator names, and nothing else.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_URL = "http://127.0.0.1:8091/v1"

#: The host context, captured at register() time (never imported from hermes internals).
_CTX: Any = None


def bind(ctx: Any) -> None:
    """Hold the host facade for later calls. Registration itself writes nothing."""
    global _CTX
    _CTX = ctx


def ctx_llm() -> Any:
    return getattr(_CTX, "llm", None) if _CTX is not None else None


def register_cli(subparser: argparse.ArgumentParser) -> None:
    """``hermes reel <action>`` - only ``plan`` exists."""
    subs = subparser.add_subparsers(dest="reel_action")
    plan = subs.add_parser("plan", help="Plan comic episodes from this machine's Hermes history")
    plan.add_argument(
        "--dry-run",
        action="store_true",
        help="plan and write artefacts without any side effect beyond the output directory",
    )
    plan.add_argument("--days", type=int, default=7, help="window in days (default 7)")
    plan.add_argument("--episodes", type=int, default=3, help="how many stories to plan")
    plan.add_argument("--format", default="strip", choices=("strip", "chapter"))
    plan.add_argument("--data-dir", default="", help="where to write artefacts")
    plan.add_argument("--llm-url", default=DEFAULT_LOCAL_URL, help="local route for redaction")
    plan.add_argument("--max-deep-events", type=int, default=90)
    plan.add_argument("--json", action="store_true", help="print the metrics JSON")
    subparser.set_defaults(func=reel_command)


def reel_command(args: argparse.Namespace) -> int:
    action = getattr(args, "reel_action", None)
    if action != "plan":
        print("Usage: hermes reel plan --dry-run [--days N] [--episodes N]")
        return 2
    if not getattr(args, "dry_run", False):
        print("This command only plans: pass --dry-run.")
        return 2

    llm = ctx_llm()
    if llm is None:
        print("ctx.llm is unavailable in this process; run this through `hermes reel plan`.")
        return 1

    # Imported here: the pipeline is a dev/CLI surface and must not load during the
    # host's capability probe.
    try:
        from adapters.hermes.llm import OpenAICompatLLMClient
        from adapters.hermes.pipeline import PipelineConfig, run_pipeline
    except ImportError:  # directory install: the plugin dir is not on sys.path
        here = Path(__file__).resolve().parents[2]
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))
        from adapters.hermes.llm import OpenAICompatLLMClient
        from adapters.hermes.pipeline import PipelineConfig, run_pipeline

    from adapters.hermes.plugin_llm import PluginLLMClient

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else Path.home() / ".hermes" / "reel"
    writer = PluginLLMClient(llm)
    local = OpenAICompatLLMClient(base_url=args.llm_url, model="auto")

    config = PipelineConfig(
        data_dir=data_dir,
        days=args.days,
        format=args.format,
        episodes=max(1, args.episodes),
        max_deep_events=args.max_deep_events,
        use_model=True,
        llm=local,
        writer_llm=writer,
    )
    result = run_pipeline(config)

    usage = writer.usage()
    print(f"episodes: {len(result.episodes)}  panels: {len(result.ir.panels) if result.ir else 0}")
    for episode in result.episodes:
        print(f"  {episode['number']}. {episode['title']!r} ({episode['title_source']}, {episode['panels']} panels)")
    print(f"writer: ctx.llm, {usage['calls']} calls, {usage['prompt_tokens']} prompt tokens, "
          f"{usage['completion_tokens']} completion tokens, "
          f"max {usage['max_prompt_tokens_per_call']} prompt tokens in one call")
    if result.problems:
        print("problems:")
        for problem in result.problems:
            print(f"  - {problem}")
    if args.json:
        print(json.dumps({"usage": usage, "episodes": result.episodes}, indent=2, sort_keys=True))
    return 0 if not result.problems else 1
