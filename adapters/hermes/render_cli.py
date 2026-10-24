"""``hermes reel render`` and ``hermes reel kit`` (M2 P7).

render: a planned episode (from ``hermes reel plan``) becomes lettered comic files:
1. **Clear the cast.** Every character needs an approved kit; a real person in public mode needs consent; an untested style needs an explicit opt-in.
2. **Prompt each panel** in the approved bake-off shape.
3. **Render** through the user's own ``image_generate``, with a per-episode image budget.
4. **Check each panel with vision**, regenerating a failed panel up to ``--retries`` times. A panel that still fails flags the episode; the files are still written for review, marked FLAGGED.
5. **Letter** the panels: balloons, captions, tails.
6. **Export** the page, the strip, the social sizes, a caption draft and a sidecar.

Nothing is posted. The owner reviews the files and shares them by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]


def _data_root(explicit: str, default_dir: Callable[[], Path]) -> Path:
    return Path(explicit).expanduser() if explicit else default_dir()


def register_render_cli(subs: Any) -> None:
    render = subs.add_parser("render", help="Render a planned episode into lettered comic files")
    render.add_argument("--plan-dir", required=True, help="the --data-dir of a `hermes reel plan` run")
    render.add_argument("--episode", type=int, default=1)
    render.add_argument("--style", default="anime")
    render.add_argument("--out", default="", help="output folder (default: <plan-dir>/render-<episode>-<style>)")
    render.add_argument("--budget", type=int, default=12, help="max new images for this episode")
    render.add_argument("--retries", type=int, default=1, help="regenerations per failed panel")
    render.add_argument("--public", action="store_true", help="public mode: real people need consent")
    render.add_argument("--allow-untested-style", action="store_true")
    render.add_argument("--assets-dir", default="", help="user styles/kits/approvals (default: plugin data dir)")

    kit = subs.add_parser("kit", help="List, add or approve character kits")
    kit_subs = kit.add_subparsers(dest="kit_action")
    listing = kit_subs.add_parser("list", help="List kits and their approval state")
    add = kit_subs.add_parser("add", help="Add a kit from an existing sheet image")
    add.add_argument("key")
    add.add_argument("--name", required=True)
    add.add_argument("--style", required=True)
    add.add_argument("--sheet", required=True, help="path to the reference sheet image")
    add.add_argument("--description", default="")
    add.add_argument("--real-person", action="store_true")
    add.add_argument("--owner", action="store_true", help="this kit is you (counts as consent)")
    add.add_argument("--public-consent", action="store_true", help="consent for public renders is recorded")
    add.add_argument("--licence", default="owner-provided")
    approve = kit_subs.add_parser("approve", help="Approve a kit's sheet for a style (owner action)")
    approve.add_argument("key")
    approve.add_argument("--style", required=True)
    approve.add_argument("--yes", action="store_true", help="confirm you have looked at the sheet")
    for sub in (kit, listing, add, approve):
        sub.add_argument("--assets-dir", default="")


def _assets(args: argparse.Namespace, default_dir: Callable[[], Path]):
    from canon.assets import Approvals, load_kits, load_styles

    root = _data_root(getattr(args, "assets_dir", ""), default_dir)
    styles = load_styles(REPO / "styles", root / "styles")
    kits = load_kits(REPO / "kits", root / "kits")
    approvals = Approvals.load(root / "approvals.json")
    return root, styles, kits, approvals


def kit_command(args: argparse.Namespace, default_dir: Callable[[], Path]) -> int:
    root, styles, kits, approvals = _assets(args, default_dir)
    action = getattr(args, "kit_action", None)
    if action == "list" or action is None:
        for key, kit in sorted(kits.items()):
            states = []
            for style in sorted(kit.sheets):
                try:
                    ok = approvals.is_approved(kit, style)
                except Exception:  # noqa: BLE001 - a missing sheet is "not approved"
                    ok = False
                states.append(f"{style}={'approved' if ok else 'NOT approved'}")
            person = " real-person" + (" owner" if kit.owner else "") + (" consent" if kit.public_consent else "") if kit.real_person else ""
            print(f"{key:16} {kit.name:16} {', '.join(states)}{person} [{kit.source}]")
        return 0
    if action == "add":
        sheet = Path(args.sheet).expanduser()
        if not sheet.is_file():
            print(f"sheet not found: {sheet}")
            return 2
        if args.style not in styles:
            print(f"unknown style {args.style!r}; known: {', '.join(sorted(styles))}")
            return 2
        target = root / "kits" / args.key
        target.mkdir(parents=True, exist_ok=True)
        existing = {}
        if (target / "kit.json").is_file():
            existing = json.loads((target / "kit.json").read_text(encoding="utf-8"))
        copied = target / f"{args.style}{sheet.suffix.lower() or '.png'}"
        shutil.copyfile(sheet, copied)
        sheets = dict(existing.get("sheets", {}))
        sheets[args.style] = copied.name
        data = {
            "name": args.name,
            "role": existing.get("role", "cast"),
            "description": args.description or existing.get("description", ""),
            "sheets": sheets,
            "real_person": bool(args.real_person or existing.get("real_person")),
            "owner": bool(args.owner or existing.get("owner")),
            "public_consent": bool(args.public_consent or existing.get("public_consent")),
            "licence": args.licence,
        }
        (target / "kit.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"kit {args.key!r} saved ({args.style}); it renders only after `hermes reel kit approve {args.key} --style {args.style} --yes`")
        return 0
    if action == "approve":
        kit = kits.get(args.key)
        if kit is None:
            print(f"unknown kit {args.key!r}")
            return 2
        sheet = kit.sheet(args.style)
        if not args.yes:
            print(f"Look at {sheet} first. If it is right, re-run with --yes.")
            return 2
        digest = approvals.approve(kit, args.style)
        print(f"approved {args.key} in {args.style} (sheet sha256 {digest[:12]})")
        return 0
    print("Usage: hermes reel kit list|add|approve")
    return 2


def render_command(args: argparse.Namespace, *, ctx: Any, default_dir: Callable[[], Path]) -> int:
    from adapters.hermes.images import host_generator
    from adapters.hermes.vision import VisionError, host_vision
    from canon.assets import clear_to_render
    from canon.export import export_episode
    from canon.letterer import letter_panel
    from canon.panel_check import TIGHT_QUESTION, check_question, interpret
    from canon.panel_prompt import build_episode_requests, episode_cast
    from canon.render import PanelRenderer, RenderReport, write_render_manifest
    from PIL import Image

    dispatch = getattr(ctx, "dispatch_tool", None)
    if dispatch is None:
        print("ctx.dispatch_tool is unavailable; run this through `hermes reel render`.")
        return 1
    # A CLI subcommand runs before the agent loads its tools, so the registry is empty and
    # every dispatch answers "Unknown tool". ``tools.registry`` is a documented public plugin
    # surface; discovery is idempotent.
    try:
        from tools.registry import discover_builtin_tools

        discover_builtin_tools()
    except Exception as exc:  # noqa: BLE001 - report, then let dispatch fail visibly
        print(f"warning: could not load the host tools ({type(exc).__name__}: {exc})")
    plan_dir = Path(args.plan_dir).expanduser()
    ir_path = plan_dir / f"script-ir-{args.episode}.json"
    if not ir_path.is_file():
        print(f"no planned episode at {ir_path}; run `hermes reel plan --dry-run` first")
        return 2
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    title = ir.get("logline") or "Scrollback Reel"
    root, styles, kits, approvals = _assets(args, default_dir)
    style = styles.get(args.style)
    if style is None:
        print(f"unknown style {args.style!r}; known: {', '.join(sorted(styles))}")
        return 2

    cast = episode_cast(ir)
    from canon.panel_prompt import _kit_for  # same name resolution as the prompts

    cast_kits, missing = [], []
    for name in cast:
        kit = _kit_for(name, kits)
        (cast_kits.append(kit) if kit else missing.append(name))
    problems = [f"no character kit for {name!r} (add one with `hermes reel kit add`)" for name in missing]
    problems += clear_to_render(style=style, kits=cast_kits, approvals=approvals, public=args.public,
                                allow_untested_style=args.allow_untested_style)
    if problems:
        print("Not cleared to render:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    requests, prompt_problems = build_episode_requests(ir, style=style, kits=kits)
    if prompt_problems:
        for problem in prompt_problems:
            print(f"  - {problem}")
        return 1

    out = Path(args.out).expanduser() if args.out else plan_dir / f"render-{args.episode}-{style.key}"
    raw_dir = out / "raw"
    renderer = PanelRenderer(host_generator(dispatch), cache_dir=root / "cache" / "images", budget=args.budget)
    ask = host_vision(dispatch)
    report = RenderReport()
    descriptions = {name: getattr(_kit_for(name, kits), "description", "") for name in cast}
    panels_by_id = {p.get("id"): p for p in ir.get("panels", [])}
    checks: list[dict[str, Any]] = []
    lettered: list[Image.Image] = []
    flagged: list[str] = []

    for request in requests:
        final_path, final_check = None, None
        for attempt in range(0, max(0, args.retries) + 1):
            path = renderer.render_one(request, raw_dir, report, attempt_tag=f"retry{attempt}" if attempt else "")
            if path is None:
                break
            try:
                answer = ask(path, check_question(list(request.cast), descriptions))
                check = interpret(
                    request.panel_id, list(request.cast), answer,
                    tighten=lambda name, p=path: ask(p, TIGHT_QUESTION.format(name=name)),
                )
            except VisionError as exc:
                from canon.panel_check import PanelCheck

                check = PanelCheck(panel_id=request.panel_id, problems=[f"vision check unavailable: {exc}"])
            final_path, final_check = path, check
            if check.passed:
                break
        if final_path is None or final_check is None:
            flagged.append(f"{request.panel_id}: not rendered")
            continue
        report.rendered[request.panel_id] = final_path
        checks.append(final_check.as_dict())
        if not final_check.passed:
            flagged.append(f"{request.panel_id}: {'; '.join(final_check.problems)}")
        panel = panels_by_id.get(request.panel_id, {})
        lines = [(str(l.get("speaker", "")), str(l.get("text", ""))) for l in panel.get("lines", [])]
        image, letter_report = letter_panel(
            Image.open(final_path),
            heads=final_check.heads,
            free=final_check.free or [[0.05, 0.01, 0.95, 0.25]],
            keep_out=final_check.keep_out,
            caption=str(panel.get("caption", "")),
            lines=lines,
        )
        checks[-1]["lettering"] = letter_report.as_dict()
        if not letter_report.complete:
            flagged.append(f"{request.panel_id}: could not place {', '.join(letter_report.unplaced)}")
        lettered.append(image)

    write_render_manifest(out / "render-manifest.json", requests, report)
    if not lettered:
        print("nothing rendered:")
        for item in report.failures + flagged:
            print(f"  - {item}")
        return 1
    if flagged:
        ir = dict(ir, flagged=flagged)
    exports = export_episode(lettered, out_dir=out, title=title, ir=ir, style=style.key,
                             render_report=report.as_dict(), checks=checks)
    print(f"rendered {len(lettered)}/{len(requests)} panels in {style.key}: {report.calls} new images, "
          f"{report.cache_hits} from cache, {report.retries} retries")
    print(f"files: {out}")
    for name in ("page", "strip", "x-wide", "linkedin-portrait", "discord", "caption", "sidecar"):
        print(f"  {name:18} {exports.files[name]}")
    if flagged or report.failures:
        print("FLAGGED - review before sharing:")
        for item in flagged + report.failures:
            print(f"  - {item}")
        return 1
    return 0
