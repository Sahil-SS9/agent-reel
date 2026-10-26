"""V14 (25/10/26): style library as raw prompt files; any style usable with any kit."""

import json
from pathlib import Path

from canon.assets import Approvals, clear_to_render, load_kits, load_styles
from canon.panel_prompt import build_panel_request

REPO = Path(__file__).resolve().parents[1]


def test_builtin_library_has_about_a_dozen_styles_with_placeholder():
    styles = load_styles(REPO / "styles")
    assert len(styles) >= 12
    raw = [s for s in styles.values() if s.raw_template]
    assert len(raw) >= 10 and all("[INSERT CHARACTERS, ACTION AND SCENE HERE]" in s.raw_template for s in raw)
    assert "ukiyo-e-folktale" in styles and styles["ukiyo-e-folktale"].status == "experimental"
    assert all(s.licence != "unknown" for s in styles.values())


def test_user_style_md_overrides_and_loads(tmp_path):
    d = tmp_path / "styles" / "my-style"
    d.mkdir(parents=True)
    (d / "style.md").write_text("---\nname: my-style\ntitle: Mine\nlicence: mine\n---\nPaint [INSERT CHARACTERS, ACTION AND SCENE HERE] in gouache. [MOOD]\n")
    styles = load_styles(REPO / "styles", tmp_path / "styles")
    assert styles["my-style"].source == "user" and "gouache" in styles["my-style"].raw_template


def _kits(tmp_path):
    d = tmp_path / "kits" / "sahil"
    d.mkdir(parents=True)
    (d / "anime.jpg").write_bytes(b"x")
    (d / "kit.json").write_text(json.dumps({"name": "Sahil", "sheets": {"anime": "anime.jpg"}, "licence": "owner", "real_person": True, "owner": True}))
    return load_kits(REPO / "kits", tmp_path / "kits")


def test_raw_template_receives_scene_and_identity_only_note(tmp_path):
    style = load_styles(REPO / "styles")["ukiyo-e-folktale"]
    kits = _kits(tmp_path)
    req = build_panel_request({"id": "p1", "role": "climax", "cast": ["Sahil"], "caption": "c", "lines": []}, style=style, kits=kits)
    assert "[INSERT CHARACTERS" not in req.prompt and "SAHIL on the" in req.prompt
    assert "ukiyo-e" in req.prompt and "redraw them entirely in the art style" in req.prompt
    assert "COMIC PANEL RULES" in req.prompt and "explosive" in req.prompt
    assert req.references and req.references[0].name == "anime.jpg"


def test_fallback_sheet_must_be_approved(tmp_path):
    styles = load_styles(REPO / "styles")
    kits = _kits(tmp_path)
    approvals = Approvals.load(tmp_path / "approvals.json")
    problems = clear_to_render(style=styles["saga-noir"], kits=[kits["sahil"]], approvals=approvals, public=False, allow_untested_style=True)
    assert any("'anime' is not approved" in p for p in problems)
    approvals.approve(kits["sahil"], "anime")
    assert clear_to_render(style=styles["saga-noir"], kits=[kits["sahil"]], approvals=approvals, public=False, allow_untested_style=True) == []


def test_the_style_catalogue_matches_the_idea_deck_scale():
    """Sahil, 26/10/26: the style library should be as broad as the idea deck (50+)."""
    from pathlib import Path

    from canon.assets import load_styles

    styles = load_styles(Path("styles"))
    assert len(styles) >= 50, f"only {len(styles)} styles"
    # Every raw-template style must carry the insert mark, or the loader rejects it.
    for key, style in styles.items():
        if style.raw_template:
            assert "[INSERT CHARACTERS, ACTION AND SCENE HERE]" in style.raw_template, key
        else:
            assert style.prompt_block.strip(), key
    # The untested ones are refused unless the caller opts in - that is the safety net.
    untested = [k for k, s in styles.items() if not s.tested]
    assert len(untested) >= 40, "expected most styles to be honestly marked untested"


def test_a_dry_run_kit_does_not_break_the_tool(tmp_path):
    """26/10/26 release check: a kit created with --dry-run has no sheet yet; it must be
    skipped by the loader instead of raising for every later command."""
    import json

    from canon.assets import load_kits

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    draft = user / "kits" / "test-runner"
    draft.mkdir(parents=True)
    (draft / "kit.json").write_text(json.dumps({
        "name": "Test Runner", "role": "cast", "description": "draft",
        "sheets": {}, "licence": "MIT",
    }), encoding="utf-8")

    kits = load_kits(builtin / "kits", user / "kits")
    assert "test-runner" not in kits
