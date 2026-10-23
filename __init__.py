"""Hermes Scrollback Reel plugin entry point (round 5, Step 0).

Registers ONE surface: the CLI command ``hermes reel plan --dry-run``. No hooks, no slash
commands, no tools, no schedule. The command runs the reel pipeline with the writer, title
and entailment calls on ``ctx.llm`` - the production model path - while redaction stays on
the local route, so only post-gate text reaches the host model.

Imports stay inside ``register()``: a directory install mounts this file as
``hermes_plugins.<slug>`` with the plugin dir as the search location (so the relative
import resolves), while a dev checkout and the host's capability probe need the absolute
fallback. A module-level try/except would make a pytest session treat the repo root as a
package and die at collection.
"""

from __future__ import annotations


def register(ctx) -> None:
    try:
        from .adapters.hermes.reel_cli import bind, reel_command, register_cli
    except ImportError:  # dev checkout, or the host's capability probe
        from adapters.hermes.reel_cli import bind, reel_command, register_cli  # type: ignore[no-redef]

    bind(ctx)
    ctx.register_cli_command(
        name="reel",
        help="Plan comic episodes from this machine's Hermes history",
        setup_fn=register_cli,
        handler_fn=reel_command,
        description=(
            "Plans weekly comic episodes from local Hermes history. Read-only on ~/.hermes: "
            "the plan is written to the directory you name, and the writer runs on ctx.llm."
        ),
    )
