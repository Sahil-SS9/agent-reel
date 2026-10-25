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


def _default_data_dir() -> Path:
    """The plugin's own data directory (decision P1), never a hand-built ~/.hermes path."""
    try:
        from plugins.plugin_storage import plugin_data_dir  # host surface
    except ImportError:
        try:
            from hermes_plugins.scrollback_reel.plugins.plugin_storage import (  # type: ignore
                plugin_data_dir,
            )
        except ImportError:
            return Path.home() / ".local" / "share" / "scrollback-reel"
    return Path(plugin_data_dir("scrollback-reel"))


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
    plan.add_argument("--since", default="", help="window start, YYYY-MM-DD (overrides --days)")
    plan.add_argument("--until", default="", help="window end, YYYY-MM-DD (default now)")
    plan.add_argument("--episodes", type=int, default=3, help="how many stories to plan")
    plan.add_argument("--format", default="strip", choices=("strip", "chapter"))
    plan.add_argument("--data-dir", default="", help="where to write artefacts")
    plan.add_argument("--llm-url", default=DEFAULT_LOCAL_URL, help="local route for redaction")
    plan.add_argument("--max-deep-events", type=int, default=90)
    plan.add_argument("--json", action="store_true", help="print the metrics JSON")
    plan.add_argument("--harness", default="hermes",
                      help="history to read: hermes, claude-code, codex, opencode, pi, jsonl - or several, comma-separated")
    plan.add_argument("--harness-root", action="append", default=[], metavar="NAME=PATH",
                      help="where a harness keeps its logs, e.g. codex=~/.codex/sessions")
    plan.add_argument("--mapping", default="", help="jsonl harness: mapping file (glob + field paths)")
    plan.add_argument("--wording", default="meaning", choices=("meaning", "strict"),
                      help="meaning (V7, default): true in meaning, plain English; strict: close to the source words")
    check = subs.add_parser(
        "eval-grounding",
        help="Run the caption/line grounding eval against the host model (reads no history)",
    )
    check.add_argument("--json-out", default="", help="where to write the eval report")
    check.add_argument("--meaning", action="store_true", help="judge in meaning mode (V7) and add the plain-English cases")
    try:
        from adapters.hermes.render_cli import register_render_cli
    except ImportError:
        _import_repo()
        from adapters.hermes.render_cli import register_render_cli
    register_render_cli(subs)
    subparser.set_defaults(func=reel_command)


def _import_repo() -> None:
    try:
        import canon  # noqa: F401
    except ImportError:  # directory install: the plugin dir is not on sys.path
        here = Path(__file__).resolve().parents[2]
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))


def eval_grounding_command(args: argparse.Namespace) -> int:
    """The grounding eval through the production judge (round 10).

    The eval script's own model option is a local OpenAI-compatible route; the plugin's
    judge is ctx.llm. Only this command measures the judge the pipeline actually uses.
    Synthetic cases only: no history is read and no network call is made beyond ctx.llm.
    """
    llm = ctx_llm()
    if llm is None:
        print("ctx.llm is unavailable in this process; run this through `hermes reel eval-grounding`.")
        return 1
    _import_repo()
    import importlib.util

    from adapters.hermes.plugin_llm import PluginLLMClient
    from canon.grounding import ClaimGate

    path = Path(__file__).resolve().parents[2] / "eval" / "grounding" / "run.py"
    spec = importlib.util.spec_from_file_location("reel_grounding_eval", path)
    if spec is None or spec.loader is None:
        print(f"grounding eval not found at {path}")
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    client = PluginLLMClient(llm)
    report = module.run(ClaimGate(client, allow=module.EVAL_CAST, meaning=bool(getattr(args, "meaning", False))))  # type: ignore[arg-type]
    report["usage"] = client.usage()
    print(f"grounding eval (judge: ctx.llm): {report['cases']} cases")
    print(f"  grounded lines accepted : {report['grounded_lines_passed']}/{report['cases']}")
    print(f"  paraphrases accepted    : {report['paraphrases_accepted']}/{report['paraphrase_cases']}")
    print(f"  invented lines refused  : {report['invented_lines_refused']}/{report['cases']}")
    if report.get("meaning_mode"):
        print(f"  plain-English accepted  : {report['meaning_accepted']}/{report['meaning_cases']}")
    for row in report["released_unsupported"]:
        print(f"  RELEASED: case {row['case']}: {row['line']}")
    for row in report["rejected_supported"]:
        print(f"  refused true line: case {row['case']}: {row['line']} ({row['reason']})")
    print(f"  judge calls: {client.calls}, max prompt tokens {client.max_prompt_tokens_per_call}")
    print("GATE " + ("PASSED: 0 unsupported claims released" if report["ok"] else "FAILED"))
    if args.json_out:
        out = Path(args.json_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return 0 if report["ok"] else 1


def _kit_voices() -> dict[str, str]:
    """Voices from built-in and user character kits (V11)."""
    try:
        from canon.assets import load_kits

        repo = Path(__file__).resolve().parents[2]
        kits = load_kits(repo / "kits", _default_data_dir() / "kits")
    except Exception:  # noqa: BLE001 - voices are optional
        return {}
    return {kit.name: kit.voice for kit in kits.values() if kit.voice}


def _harness_options(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    options: dict[str, dict[str, Any]] = {}
    for item in getattr(args, "harness_root", []) or []:
        name, _sep, path = str(item).partition("=")
        if name and path:
            options.setdefault(name.strip(), {})["root"] = path.strip()
    if getattr(args, "mapping", ""):
        mapping = json.loads(Path(args.mapping).expanduser().read_text(encoding="utf-8"))
        options.setdefault("jsonl", {})["mapping"] = mapping
    return options


def reel_command(args: argparse.Namespace) -> int:
    action = getattr(args, "reel_action", None)
    if action == "eval-grounding":
        return eval_grounding_command(args)
    if action in {"render", "kit", "sources", "book", "styles"}:
        _import_repo()
        from adapters.hermes import render_cli

        if action == "kit":
            return render_cli.kit_command(args, _default_data_dir, ctx=_CTX)
        if action == "sources":
            return render_cli.sources_command(args, _default_data_dir)
        if action == "book":
            return render_cli.book_command(args, _default_data_dir)
        if action == "styles":
            return render_cli.styles_command(args, _default_data_dir)
        return render_cli.render_command(args, ctx=_CTX, default_dir=_default_data_dir)
    if action != "plan":
        print("Usage: hermes reel plan --dry-run | render --plan-dir DIR | sources | styles | book | kit list|add|create|approve|contribute | eval-grounding")
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

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else _default_data_dir()
    # V4: a chapter needs about twice the writer calls of a strip per story tried.
    writer = PluginLLMClient(llm, max_calls=300 if getattr(args, "format", "strip") == "chapter" else 150)
    local = OpenAICompatLLMClient(base_url=args.llm_url, model="auto")

    def _day(value: str) -> float | None:
        if not value:
            return None
        from datetime import datetime, timezone

        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

    try:
        since, until = _day(getattr(args, "since", "")), _day(getattr(args, "until", ""))
    except ValueError:
        print("--since/--until must be YYYY-MM-DD")
        return 2

    config = PipelineConfig(
        data_dir=data_dir,
        days=args.days,
        since=since,
        until=until,
        format=args.format,
        wording=getattr(args, "wording", "meaning"),
        harnesses=tuple(h.strip() for h in str(getattr(args, "harness", "hermes")).split(",") if h.strip()),
        harness_options=_harness_options(args),
        voices=_kit_voices(),
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
