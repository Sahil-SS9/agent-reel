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
    _register_blueprints(ctx)
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


#: D7 (amended): an optional daily or weekly strip. A blueprint is only a template in the
#: user's catalog; nothing runs until the user creates an automation from it.
_BLUEPRINT_PROMPT = (
    "Make this {cadence} Scrollback Reel strip for the owner to review. Run, in a terminal: "
    "`hermes reel plan --dry-run --days {days} --episodes 1 --format {{format}} --tone {{tone}} --data-dir PLAN_DIR` and then "
    "`hermes reel render --plan-dir PLAN_DIR --episode 1 --style {{style}}`, with "
    "PLAN_DIR a new folder under the plugin's data directory named by today's date. "
    "If the plan finds no story, say so in one line and stop: a quiet {unit} gets no strip. "
    "Report the page and caption-draft paths and any FLAGGED panels. Never post, upload or "
    "share the strip anywhere; the owner decides."
)


def _style_keys() -> tuple[str, ...]:
    """Built-in style names for the blueprint picker (V14)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent / "styles"
    keys = sorted(p.name for p in root.iterdir() if (p / "style.json").is_file() or (p / "style.md").is_file())
    return tuple(["anime"] + [k for k in keys if k != "anime"]) or ("anime",)


def _register_blueprints(ctx) -> None:
    register = getattr(ctx, "register_automation_blueprint", None)
    if register is None:  # older host: no blueprint catalog
        return
    style_slot = {"name": "style", "type": "enum", "label": "Art style", "default": "anime",
                  "options": _style_keys()}
    format_slot = {"name": "format", "type": "enum", "label": "Length", "default": "strip",
                   "options": ("strip", "chapter")}
    tone_slot = {"name": "tone", "type": "enum", "label": "Tone", "default": "auto",
                 "options": ("auto", "witty", "comical", "serious", "quirky", "epic", "wholesome", "noir")}
    time_slot = {"name": "time", "type": "time", "label": "Time", "default": "18:00"}
    register(
        "daily-strip",
        title="Scrollback Reel: daily strip",
        description="A short comic of today's real work, for you to review. Nothing is posted.",
        schedule_template="{minute} {hour} * * *",
        prompt_template=_BLUEPRINT_PROMPT.format(cadence="daily", days=1, unit="day"),
        category="daily",
        slots=[time_slot, format_slot, tone_slot, style_slot],
        deliver_default="origin",
        tags=("comic", "scrollback-reel"),
    )
    register(
        "weekly-strip",
        title="Scrollback Reel: weekly strip",
        description="A comic of the week's real work (a one-page strip or a 3-4 page chapter), for you to review. Nothing is posted.",
        schedule_template="{minute} {hour} * * {dow}",
        prompt_template=_BLUEPRINT_PROMPT.format(cadence="weekly", days=7, unit="week"),
        category="weekly",
        slots=[time_slot, {"name": "day", "type": "enum", "label": "Which day?", "default": "friday",
                                    "options": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}, format_slot, tone_slot, style_slot],
        deliver_default="origin",
        tags=("comic", "scrollback-reel"),
    )
    register(
        "monthly-book",
        title="Scrollback Reel: monthly comic book",
        description="On the 1st, collect last month's rendered episodes into one PDF comic book. Nothing is posted.",
        schedule_template="{minute} {hour} 1 * *",
        prompt_template=(
            "Make last month's Scrollback Reel comic book for the owner. Run, in a terminal: "
            "`hermes reel book --month YYYY-MM` with YYYY-MM the previous calendar month. If it "
            "says there are no rendered episodes, say so in one line and stop. Report the PDF path "
            "and the episode titles. Never post, upload or share it; the owner decides."
        ),
        category="monthly",
        slots=[time_slot],
        deliver_default="origin",
        tags=("comic", "scrollback-reel"),
    )
