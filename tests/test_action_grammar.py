"""M3: action grammar in the treatment and the panel prompt, and the deck frame reaching both."""

from types import SimpleNamespace

from canon.director import DIRECTOR_PROMPT, ROLE_ACTION, direct
from canon.ideas import draw
from canon.panel_prompt import build_panel_request


def _ir() -> dict:
    return {
        "logline": "A true story",
        "episode_id": "ep1",
        "panels": [
            {"id": "p1", "role": "setup", "cast": ["Sahil"], "caption": "", "lines": [], "setting": "the rig"},
            {"id": "p2", "role": "climax", "cast": ["Sahil"], "caption": "", "lines": [], "setting": "the rig"},
        ],
    }


def test_every_rule_panel_carries_motion_reaction_and_camera():
    treatment = direct(_ir(), story_text="the build failed, then it passed")
    for panel in treatment.panels.values():
        assert panel.motion and panel.reaction and panel.camera
    # The climax is where something is struck; a calm setup has nothing to break yet.
    assert treatment.panels["p2"].impact
    assert treatment.panels["p2"].role in ROLE_ACTION


def test_the_deck_frame_decides_the_world_and_the_villain():
    frame = draw("Sahil", 4)
    treatment = direct(_ir(), story_text="a failure and a fix", frame=frame)
    assert treatment.world == frame["world"]["label"]
    assert treatment.villain_look == frame["villain"]["look"]
    assert treatment.panels["p1"].location == frame["world"]["label"]


def test_two_different_chapters_get_different_treatments():
    one = direct(_ir(), story_text="a failure and a fix", frame=draw("Sahil", 1))
    two = direct(_ir(), story_text="a failure and a fix", frame=draw("Sahil", 2))
    assert (one.world, one.villain_name) != (two.world, two.villain_name)


def test_the_director_prompt_asks_for_action_not_poses():
    lowered = DIRECTOR_PROMPT.lower()
    for word in ("frozen moment of action", "motion", "impact", "reaction", "camera"):
        assert word in lowered
    assert "full-bleed impact frame" in lowered


def test_the_panel_prompt_carries_the_action_grammar():
    treatment = direct(_ir(), story_text="a failure and a fix", frame=draw("Sahil", 3))
    style = SimpleNamespace(
        name="anime",
        prompt_block="anime style",
        staging_rules="",
        negative_block="no text",
        raw_template="",
        key="anime",
    )
    request = build_panel_request(
        {"id": "p2", "role": "climax", "cast": [], "caption": "", "lines": [], "setting": "the rig"},
        style=style,
        kits={},
        treatment=treatment.panels["p2"],
    )
    text = request["prompt"] if isinstance(request, dict) else str(request)
    for label in ("ACTION:", "MOTION:", "IMPACT:", "REACTION:", "CAMERA:", "Full-bleed impact frame"):
        assert label in text


def test_the_page_font_scale_clears_the_readability_floor():
    """Quan D3: the font floor is a named constant with a geometric test, not a comment.

    Geometry: a chapter page is PAGE_WIDTH px wide; side-by-side panels are never narrower
    than MIN_PANEL_SHARE of it; every panel is lettered at its native width scaled by
    PAGE_FONT_SCALE. At whole-page screen size (REFERENCE_DPI) the smallest line must clear
    MIN_PAGE_POINT_SIZE.
    """
    from canon.export import MIN_PANEL_SHARE, PAGE_WIDTH
    from canon.letterer import REFERENCE_WIDTH
    from adapters.hermes.render_cli import (
        MIN_PAGE_POINT_SIZE,
        PAGE_FONT_SCALE,
        REFERENCE_DPI,
    )

    panel_native = REFERENCE_WIDTH
    on_page = PAGE_WIDTH * MIN_PANEL_SHARE
    shrink = on_page / panel_native
    smallest_font_px = 30 * (panel_native / REFERENCE_WIDTH * PAGE_FONT_SCALE) * shrink
    points = smallest_font_px / REFERENCE_DPI * 72
    assert points >= MIN_PAGE_POINT_SIZE, f"{points:.1f}pt below the {MIN_PAGE_POINT_SIZE}pt floor"
    # And the old scale is provably below it, so the test can fail.
    old_points = smallest_font_px / (PAGE_FONT_SCALE / 1.4) / REFERENCE_DPI * 72
    assert old_points < MIN_PAGE_POINT_SIZE


def test_the_villain_is_named_from_the_chapter_frame_not_invented_each_render():
    """t_ae4a9485: a new villain name each render meant a new sheet, new prompts, new art."""
    from canon.director import frame_villain

    frame = draw("Sahil", 7)
    named = frame_villain(frame)
    assert named is not None
    name, look = named
    assert name == frame["villain"]["key"].replace("-", " ").title()
    assert look == frame["villain"]["look"]
    # Same chapter, same frame, same villain - twice.
    assert frame_villain(draw("Sahil", 7)) == named


def test_a_model_supplied_villain_name_is_overridden_by_the_frame():
    """The model may still dress the panels; it does not get to rename the villain."""

    def inventive(**_kwargs):
        return {
            "villain": {"name": "The Ledger Hydra", "look": "a many-headed auditor"},
            "world": "a hall of ledgers",
            "panels": [
                {"id": "p1", "location": "a hall", "action": "they argue",
                 "villain_presence": "lurking", "shot": "full", "angle": "low"}
            ],
            "fillers": [],
        }

    frame = draw("Sahil", 7)
    treatment = direct(_ir(), story_text="work happened", complete_json=inventive, frame=frame)
    assert treatment.villain_name == frame["villain"]["key"].replace("-", " ").title()
    assert treatment.source == "model"


def test_a_villain_sheet_is_drawn_once_and_reused(tmp_path):
    """t_ae4a9485: a stable villain name means the sheet is paid for once per chapter style."""
    from types import SimpleNamespace

    from adapters.hermes.render_cli import _villain_sheet

    class Renderer:
        def __init__(self):
            self.calls = 0

        def render_one(self, request, raw_dir, report):
            self.calls += 1
            out = tmp_path / f"raw-{self.calls}.png"
            out.write_bytes(b"png")
            return out

    style = SimpleNamespace(key="anime", prompt_block="anime", negative_block="no text", refs=())
    treatment = SimpleNamespace(villain_name="The Creeping Deadline", villain_look="a long shadow")
    renderer = Renderer()
    report = SimpleNamespace()

    first = _villain_sheet(treatment, style, {}, renderer, tmp_path, tmp_path, report)
    second = _villain_sheet(treatment, style, {}, renderer, tmp_path, tmp_path, report)
    assert first is not None and second == first
    assert renderer.calls == 1, "the villain sheet was drawn twice"


def test_kit_create_loads_host_tools_before_asking_for_an_image(tmp_path, monkeypatch):
    """26/10/26: without tool discovery, kit create --source host failed with
    "Unknown tool: image_generate" while every render worked."""
    from types import SimpleNamespace

    from adapters.hermes import render_cli

    calls: list[str] = []
    monkeypatch.setattr(render_cli, "prepare_host_tools", lambda: calls.append("prepared"))
    monkeypatch.setattr(render_cli, "load_settings", lambda root: {"source": "host"})
    monkeypatch.setattr(render_cli, "_assets", lambda *a, **k: (tmp_path, {}, {}, None))

    def fake_make_generator(source, *, out_dir, host=None, **kw):
        assert host is not None, "the host route must be wired when discovery ran"
        raise SystemExit(0)

    monkeypatch.setattr("canon.providers.make_generator", fake_make_generator)
    args = SimpleNamespace(
        name="Test Runner", who="x", look="y", outfit="z", colours="c", signature="s",
        voice="v", style="anime", source="host", dry_run=False, photo=None, owner=False,
        kit_action="create",
    )
    ctx = SimpleNamespace(dispatch_tool=lambda *a, **k: "{}")
    try:
        render_cli._kit_create(args, tmp_path, {"anime": SimpleNamespace(prompt_block="anime", summary="")}, ctx)
    except SystemExit:
        pass
    assert calls == ["prepared"]


def test_a_long_line_is_split_into_balloons_that_fit():
    """t_385b3e3e: two owner lines (75 and 84 chars) had no pocket on the dense page."""
    from canon.episode import MAX_BALLOON_CHARS, split_for_balloons

    for text in (
        "So the reviewer checks the fixes, and the speed verdict waits on you. Thrilling.",
        "Noted, forgiven. Now simpler still, and write me the reply for the reviewer.",
    ):
        pieces = split_for_balloons(text)
        assert len(pieces) >= 2
        assert all(len(piece) <= int(MAX_BALLOON_CHARS * 1.35) for piece in pieces)
        # nothing invented or lost: the words survive in order
        assert " ".join(pieces).split() == " ".join(text.split()).split()


def test_a_short_line_is_left_alone():
    from canon.episode import split_for_balloons

    assert split_for_balloons("Eight contenders. Lovely.") == ["Eight contenders. Lovely."]


def test_an_api_key_is_read_through_the_host_secret_route_first(monkeypatch):
    """Catalogue rule 11: credentials come through Hermes, not a bare os.environ read."""
    from canon import providers

    calls: list[str] = []
    monkeypatch.setattr(providers, "secret_from_host", lambda name: calls.append(name) or "host-key")
    assert providers._key({}, "OPENAI_API_KEY") == "host-key"
    assert calls == ["OPENAI_API_KEY"]
    # An injected env (tests, CI) still wins, and nothing else is consulted.
    assert providers._key({"OPENAI_API_KEY": "env-key"}, "OPENAI_API_KEY") == "env-key"
    assert calls == ["OPENAI_API_KEY"]


def test_a_missing_key_names_both_routes(monkeypatch):
    import pytest

    from canon import providers
    from canon.render import RenderError

    monkeypatch.setattr(providers, "secret_from_host", lambda name: "")
    with pytest.raises(RenderError, match="hermes auth"):
        providers._key({}, "FAL_KEY")


def test_a_line_with_no_sentence_break_is_never_chopped_mid_phrase():
    """A comma is not a break: "a comic people can share" must not split before "can"."""
    from canon.episode import MAX_BALLOON_CHARS, split_for_balloons

    line = "I want a tool that turns an AI helper's real work into a comic people can share."
    pieces = split_for_balloons(line)
    assert pieces == [line]            # left whole rather than broken mid-clause
    assert len(line) > MAX_BALLOON_CHARS


def test_a_two_sentence_line_splits_at_the_sentence_end():
    from canon.episode import split_for_balloons

    pieces = split_for_balloons(
        "So the reviewer checks the fixes, and the speed verdict waits on you. Thrilling."
    )
    assert pieces == ["So the reviewer checks the fixes, and the speed verdict waits on you.", "Thrilling."]
