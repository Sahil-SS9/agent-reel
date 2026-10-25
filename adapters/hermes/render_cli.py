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
from typing import Any, Callable, Mapping

REPO = Path(__file__).resolve().parents[2]


def _data_root(explicit: str, default_dir: Callable[[], Path]) -> Path:
    return Path(explicit).expanduser() if explicit else default_dir()


def display_text(text: str) -> str:
    """Shorten long ids for the page ("1e7d3a4d01…" -> "1e7d3a4"). The sidecar keeps the full text."""
    import re

    return re.sub(r"\b([0-9a-f]{7})[0-9a-f]{5,}\b", r"\1", text)


def register_render_cli(subs: Any) -> None:
    render = subs.add_parser("render", help="Render a planned episode into lettered comic files")
    render.add_argument("--plan-dir", required=True, help="the --data-dir of a `hermes reel plan` run")
    render.add_argument("--episode", type=int, default=1)
    render.add_argument("--style", default="", help="art style (see `hermes reel styles`; default: saved choice, else anime)")
    render.add_argument("--out", default="", help="output folder (default: <plan-dir>/render-<episode>-<style>)")
    render.add_argument("--budget", type=int, default=12, help="max new images for this episode")
    render.add_argument("--retries", type=int, default=1, help="regenerations per failed panel")
    render.add_argument("--public", action="store_true", help="public mode: real people need consent")
    render.add_argument("--allow-untested-style", action="store_true", help=argparse.SUPPRESS)
    render.add_argument("--strict-styles", action="store_true", help="refuse styles not yet tested on a real render")
    render.add_argument("--literal", action="store_true", help="no director: draw what literally happened")
    render.add_argument("--assets-dir", default="", help="user styles/kits/approvals (default: plugin data dir)")
    render.add_argument("--source", default="", help="image source: host, openai, gemini, fal, comfyui (default: saved choice, else host)")
    render.add_argument("--model", default="", help="model for the source (default: the source's default)")
    render.add_argument("--workflow", default="", help="ComfyUI: workflow name in assets/workflows or a file path")
    render.add_argument("--comfyui-url", default="", help="ComfyUI server (default http://127.0.0.1:8188)")

    book = subs.add_parser("book", help="Collect a month's rendered episodes into one comic-book PDF")
    book.add_argument("--month", default="", help="YYYY-MM (default: this month)")
    book.add_argument("--all", action="store_true", help="every rendered episode found, any month")
    book.add_argument("--renders", nargs="*", default=[], help="folders to search for rendered episodes (default: plugin data dir)")
    book.add_argument("--title", default="")
    book.add_argument("--out", default="")
    book.add_argument("--assets-dir", default="")

    styles = subs.add_parser("styles", help="List art styles, show one's raw prompt, or set the default")
    styles.add_argument("--show", default="")
    styles.add_argument("--set", default="", dest="set_style")
    styles.add_argument("--assets-dir", default="")

    sources = subs.add_parser("sources", help="List image sources, check one, or set the default")
    sources.add_argument("--check", default="", help="check a source is ready (no image is made)")
    sources.add_argument("--set", default="", dest="set_source", help="save this source as the default")
    sources.add_argument("--model", default="")
    sources.add_argument("--workflow", default="")
    sources.add_argument("--comfyui-url", default="")
    sources.add_argument("--assets-dir", default="")

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


def _settings_path(root: Path) -> Path:
    return root / "settings.json"


def load_settings(root: Path) -> dict[str, Any]:
    path = _settings_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(root: Path, updates: Mapping[str, Any]) -> dict[str, Any]:
    data = load_settings(root)
    data.update({k: v for k, v in updates.items() if v not in (None, "")})
    root.mkdir(parents=True, exist_ok=True)
    _settings_path(root).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return data


def book_command(args: argparse.Namespace, default_dir: Callable[[], Path]) -> int:
    """V13: the month's rendered episodes as one comic-book PDF."""
    import time as _time

    from canon.book import build_book, find_episodes, in_month

    root = _data_root(getattr(args, "assets_dir", ""), default_dir)
    roots = [Path(p).expanduser() for p in (args.renders or [])] or [root]
    month = args.month or _time.strftime("%Y-%m")
    episodes = in_month(find_episodes(roots), "" if args.all else month)
    if not episodes:
        print(f"no rendered episodes for {month} under: {', '.join(str(r) for r in roots)}")
        return 1
    label = "Collected episodes" if args.all else _time.strftime("%B %Y", _time.strptime(month, "%Y-%m"))
    out = Path(args.out).expanduser() if args.out else root / "books" / f"scrollback-reel-{month}.pdf"
    report = build_book(episodes, out, title=args.title or "Scrollback Reel", subtitle=label)
    print(f"book: {report['pdf']} ({report['episodes']} episodes, {report['pages']} pages)")
    for name in report["titles"]:
        print(f"  - {name}")
    return 0


def styles_command(args: argparse.Namespace, default_dir: Callable[[], Path]) -> int:
    root, styles, _kits, _approvals = _assets(args, default_dir)
    if getattr(args, "show", ""):
        style = styles.get(args.show)
        if style is None:
            print(f"no style {args.show!r}")
            return 1
        print(style.raw_template or f"{style.prompt_block}\n{style.staging_rules}\n{style.negative_block}")
        return 0
    if getattr(args, "set_style", ""):
        if args.set_style not in styles:
            print(f"no style {args.set_style!r}")
            return 1
        save_settings(root, {"style": args.set_style})
        print(f"default style: {args.set_style}")
        return 0
    current = load_settings(root).get("style", "anime")
    print("Art styles (tested = proven on a real render; experimental = ready to try):")
    for key, style in sorted(styles.items()):
        mark = "*" if key == current else " "
        state = "tested" if style.tested else "experimental"
        print(f" {mark} {key:20} {state:12} {style.title}" + (f" - {style.summary}" if style.summary else "") + (" (yours)" if style.source == "user" else ""))
    print(f"Add your own: put a style.md (a raw prompt with the line [INSERT CHARACTERS, ACTION AND SCENE HERE]) in {root / 'styles' / '<name>'}/")
    print("See one: hermes reel styles --show <name>; set the default: hermes reel styles --set <name>")
    return 0


def sources_command(args: argparse.Namespace, default_dir: Callable[[], Path]) -> int:
    from canon.providers import SOURCES, check_source

    root = _data_root(getattr(args, "assets_dir", ""), default_dir)
    settings = load_settings(root)
    options = {"workflow": args.workflow or settings.get("workflow", ""),
               "base_url": args.comfyui_url or settings.get("comfyui_url", "")}
    if args.set_source:
        if args.set_source not in SOURCES:
            print(f"unknown source {args.set_source!r}; choose one of {', '.join(SOURCES)}")
            return 2
        saved = save_settings(root, {"source": args.set_source, "model": args.model,
                                     "workflow": args.workflow, "comfyui_url": args.comfyui_url})
        print(f"default image source: {saved['source']}" + (f" ({saved['model']})" if saved.get("model") else ""))
        return 0
    if args.check:
        report = check_source(args.check, options=options)
        print(json.dumps(report, indent=1))
        return 0 if report.get("ready") else 1
    current = settings.get("source", "host")
    print("Image sources (tested = real images made through it; mapped = request shapes implemented, not yet run for real):")
    for spec in SOURCES.values():
        mark = "*" if spec.key == current else " "
        env = f"  needs {', '.join(spec.env)}" if spec.env else ""
        print(f" {mark} {spec.key:8} {spec.status:8} {spec.label} - {spec.approx_cost}; up to {spec.max_references} reference sheets{env}")
    print("Set the default with: hermes reel sources --set <key> [--model M]")
    return 0


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


def _story_text(plan_dir: Path, episode: int, ir: Mapping[str, Any]) -> str:
    """Post-gate text the director may read: the episode's facts and its own words."""
    parts: list[str] = [str(ir.get("logline", ""))]
    trace = plan_dir / f"episode-{episode}-trace.json"
    if trace.is_file():
        try:
            data = json.loads(trace.read_text(encoding="utf-8"))
            parts += [str(f.get("sentence", "")) for f in data.get("facts", [])]
        except (OSError, json.JSONDecodeError):
            pass
    for panel in ir.get("panels", []) or []:
        parts.append(str(panel.get("caption", "")))
        parts += [str(l.get("text", "")) for l in panel.get("lines", [])]
    return "\n".join(p for p in parts if p.strip())


def _villain_sheet(treatment: Any, style: Any, kits: Mapping[str, Any], renderer: Any, root: Path, raw_dir: Path, report: Any) -> Path | None:
    """One reference sheet per villain and style, made once and reused (V3).

    Villains are fictional creatures, never people, so no likeness approval applies. The
    sheet is cached under the plugin data dir and listed in the render output for review.
    """
    import re

    from canon.panel_prompt import PanelRequest

    slug = re.sub(r"[^a-z0-9]+", "-", treatment.villain_name.lower()).strip("-") or "villain"
    target = root / "kits" / f"villain-{slug}" / f"{style.key}.png"
    if target.is_file():
        return target
    builtin = kits.get(slug) or kits.get(slug.removeprefix("the-"))
    if builtin is not None and style.key in builtin.sheets and builtin.sheets[style.key].is_file():
        return builtin.sheets[style.key]
    style_ref = next((ref for ref in style.refs if Path(ref).is_file()), None)
    prompt = (
        f"Character reference sheet of a comic villain: {treatment.villain_look}. "
        "Front view, three-quarter view and side view, plus three expressions, on a plain "
        "light background. A creature or force, not a human. "
        f"{style.prompt_block} Match the art style of the reference sheet exactly. "
        f"{style.negative_block}"
    )
    request = PanelRequest(panel_id=f"villain-{slug}", prompt=prompt,
                           references=(Path(style_ref),) if style_ref else (), cast=(), positions={}, aspect="landscape")
    produced = renderer.render_one(request, raw_dir, report)
    if produced is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, target)
    (target.parent / "kit.json").write_text(json.dumps({
        "name": treatment.villain_name, "role": "villain", "description": treatment.villain_look,
        "sheets": {style.key: target.name}, "real_person": False, "generated": True,
        "licence": "generated for this project; fictional",
    }, indent=1) + "\n", encoding="utf-8")
    return target


def render_command(args: argparse.Namespace, *, ctx: Any, default_dir: Callable[[], Path]) -> int:
    from adapters.hermes.images import host_generator
    from adapters.hermes.vision import VisionError, host_vision
    from canon.assets import clear_to_render
    from canon.export import export_episode
    from canon.letterer import letter_panel
    from canon.panel_check import LETTER_QUESTION, TIGHT_QUESTION, check_question, interpret
    from canon.panel_prompt import build_episode_requests, episode_cast
    from canon.render import PanelRenderer, RenderError, RenderReport, write_render_manifest
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
    trace_path = plan_dir / f"episode-{args.episode}-trace.json"
    if trace_path.is_file():
        try:
            arc = json.loads(trace_path.read_text(encoding="utf-8")).get("arc") or {}
            ir["episode_time"] = arc.get("resolved") or arc.get("opened")
        except (OSError, json.JSONDecodeError):
            pass
    root, styles, kits, approvals = _assets(args, default_dir)
    args.style = args.style or load_settings(root).get("style", "anime")
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
                                allow_untested_style=args.allow_untested_style or not getattr(args, "strict_styles", False))
    if not style.tested:
        print(f"note: style {style.key!r} has not been tested with your image source yet; check the panels before sharing")
    if problems:
        print("Not cleared to render:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    out = Path(args.out).expanduser() if args.out else plan_dir / f"render-{args.episode}-{style.key}"
    raw_dir = out / "raw"
    settings = load_settings(root)
    source = getattr(args, "source", "") or settings.get("source", "host")
    model = getattr(args, "model", "") or (settings.get("model", "") if source == settings.get("source") else "")
    from canon.providers import make_generator

    try:
        generator = make_generator(
            source, out_dir=root / "cache" / "source-out", model=model, host=host_generator(dispatch),
            options={"workflow": getattr(args, "workflow", "") or settings.get("workflow", ""),
                     "base_url": getattr(args, "comfyui_url", "") or settings.get("comfyui_url", "")},
        )
    except RenderError as exc:
        print(f"Image source problem: {exc}")
        return 1
    print(f"image source: {source}" + (f" ({model})" if model else ""))
    # The cache key includes the source, so switching source never reuses another's images.
    renderer = PanelRenderer(generator, cache_dir=root / "cache" / "images" / (source if source != "host" else ""), budget=args.budget)
    report = RenderReport()

    # V1/V3: the director decides how each panel looks (villain, world, shot, angle). The
    # words are untouched. Without a model, a rule-based treatment is used.
    treatment = None
    villain = None
    if not getattr(args, "literal", False):
        from canon.director import direct

        story_text = _story_text(plan_dir, args.episode, ir)
        llm = getattr(ctx, "llm", None)
        complete_json = None
        if llm is not None:
            from adapters.hermes.plugin_llm import PluginLLMClient

            complete_json = PluginLLMClient(llm).complete_json
        treatment = direct(ir, story_text=story_text, complete_json=complete_json)
        out.mkdir(parents=True, exist_ok=True)
        (out / "treatment.json").write_text(json.dumps(treatment.as_dict(), indent=1) + "\n", encoding="utf-8")
        sheet = _villain_sheet(treatment, style, kits, renderer, root, raw_dir, report)
        if sheet is not None:
            villain = (treatment.villain_name, treatment.villain_look, sheet)
        else:
            print(f"warning: no sheet for villain {treatment.villain_name!r}; panels drawn without it")

    requests, prompt_problems = build_episode_requests(ir, style=style, kits=kits, treatment=treatment, villain=villain)
    if prompt_problems:
        for problem in prompt_problems:
            print(f"  - {problem}")
        return 1

    ask = host_vision(dispatch)
    descriptions = {name: getattr(_kit_for(name, kits), "description", "") for name in cast}
    if villain is not None:
        descriptions[villain[0]] = f"a villain creature: {villain[1]} (not a person)"
    panels_by_id = {p.get("id"): p for p in ir.get("panels", [])}
    checks: list[dict[str, Any]] = []
    lettered: list[Image.Image] = []
    lettered_roles: list[str] = []
    flagged: list[str] = []

    for request in requests:
        final_path, final_check = None, None
        for attempt in range(0, max(0, args.retries) + 1):
            path = renderer.render_one(request, raw_dir, report, attempt_tag=f"retry{attempt}" if attempt else "")
            if path is None:
                break
            try:
                answer = ask(path, check_question(list(request.cast), descriptions))
                speakers = [str(l.get("speaker")) for l in panels_by_id.get(request.panel_id, {}).get("lines", [])]
                check = interpret(
                    request.panel_id, list(request.cast), answer,
                    tighten=lambda name, p=path: ask(p, TIGHT_QUESTION.format(name=name)),
                    require_heads=speakers,
                )
            except VisionError as exc:
                # The check could not run. That says nothing about the panel, so it is not
                # regenerated (the first real render paid for 4 needless images this way);
                # it is flagged for a human look instead.
                from canon.panel_check import PanelCheck

                final_path = path
                final_check = PanelCheck(panel_id=request.panel_id, problems=[f"vision check unavailable: {str(exc)[:160]}"])
                break
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
            caption=display_text(str(panel.get("caption", ""))),
            lines=[(speaker, display_text(text)) for speaker, text in lines],
        )
        if lines and letter_report.balloons:
            # Letterer self-check (bake-off r2): ask whether every tail points at its
            # speaker; for any miss, re-ask that head tightly and letter once more.
            speakers = ", ".join(sorted({speaker for speaker, _ in lines}))
            try:
                tmp = out / "raw" / f"{request.panel_id}-lettered-check.jpg"
                image.save(tmp, quality=85)
                misses = ask(tmp, LETTER_QUESTION.format(speakers=speakers)).get("misses") or []
                tmp.unlink(missing_ok=True)
            except VisionError:
                misses = []
            fixed_heads = dict(final_check.heads)
            for name in [str(m) for m in misses if isinstance(m, str)]:
                key = next((k for k in fixed_heads if k.lower() == name.lower()), name)
                try:
                    tight = ask(final_path, TIGHT_QUESTION.format(name=key))
                    from canon.panel_check import _box

                    box = _box(tight.get("head"))
                    if box:
                        fixed_heads[key] = box
                except VisionError:
                    pass
            if misses:
                image, letter_report = letter_panel(
                    Image.open(final_path),
                    heads=fixed_heads,
                    free=final_check.free or [[0.05, 0.01, 0.95, 0.25]],
                    keep_out=final_check.keep_out,
                    caption=display_text(str(panel.get("caption", ""))),
                    lines=[(speaker, display_text(text)) for speaker, text in lines],
                )
                checks[-1]["tail_misses_fixed"] = misses
        checks[-1]["lettering"] = letter_report.as_dict()
        if not letter_report.complete:
            flagged.append(f"{request.panel_id}: could not place {', '.join(letter_report.unplaced)}")
        lettered.append(image)
        lettered_roles.append(str(panel.get("role", "filler")) if panel else "filler")

    write_render_manifest(out / "render-manifest.json", requests, report)
    if not lettered:
        print("nothing rendered:")
        for item in report.failures + flagged:
            print(f"  - {item}")
        return 1
    if flagged:
        ir = dict(ir, flagged=flagged)
    exports = export_episode(lettered, out_dir=out, title=title, ir=ir, style=style.key,
                             render_report=report.as_dict(), checks=checks,
                             roles=lettered_roles if treatment is not None else None)
    print(f"rendered {len(lettered)}/{len(requests)} panels in {style.key}: {report.calls} new images, "
          f"{report.cache_hits} from cache, {report.retries} retries")
    print(f"files: {out}")
    pages = sorted(k for k in exports.files if k.startswith("page-"))
    print(f"  {'pages':18} {len(pages)} (+ chapter.pdf)")
    for name in ("page", "chapter-pdf", "strip", "x-wide", "linkedin-portrait", "discord", "caption", "sidecar"):
        print(f"  {name:18} {exports.files[name]}")
    if flagged or report.failures:
        print("FLAGGED - review before sharing:")
        for item in flagged + report.failures:
            print(f"  - {item}")
        return 1
    return 0
