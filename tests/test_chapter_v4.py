"""V4/V5 (25/10/26): longer chapters, wordless filler panels, comic-book page layout."""

from PIL import Image

from canon.director import direct
from canon.export import compose_pages, layout_rows

ROLES = ["setup", "insert", "hidden_problem", "insert", "diagnosis", "insert", "insert",
         "climax", "insert", "aftermath", "insert", "win"]
IR = {"logline": "A long night", "panels": [
    {"id": f"p{i}", "role": role, "caption": f"c{i}", "lines": [], "cast": ["Kensei"]}
    for i, role in enumerate(ROLES, 1)]}


def test_balanced_fillers_one_per_two_story_panels():
    t = direct(IR, story_text="the worker process was orphaned")
    assert len(t.fillers) in {len(ROLES) // 2 - 1, len(ROLES) // 2}
    ids = [p["id"] for p in IR["panels"]]
    assert all(f.after in ids[:-1] for f in t.fillers)  # never after the last panel
    assert all(f.role == "filler" for f in t.fillers)
    seq = t.sequence(IR)
    assert len(seq) == len(ROLES) + len(t.fillers)
    assert [pid for pid, _ in seq if pid in ids] == ids  # story order untouched
    pairs = [(i.shot, i.angle) for _pid, i in seq if i is not None]
    assert all(a != b for a, b in zip(pairs, pairs[1:]))


def test_calm_before_climax_and_impact_after():
    t = direct(IR, story_text="process orphaned")
    before = {f.after: f for f in t.fillers}
    # p7 precedes the climax (p8); p8 is the climax.
    if "p7" in before:
        assert "storm" in before["p7"].action
    if "p8" in before:
        assert "clash" in before["p8"].action


def test_model_fillers_off_target_fall_back_to_rules():
    def model(**_k):
        return {"panels": [], "fillers": [{"after": "p1", "action": "x", "shot": "long", "angle": "eye"}]}
    t = direct(IR, story_text="", complete_json=model)
    assert len(t.fillers) >= len(ROLES) // 2 - 1
    assert any("rule fillers" in r for r in t.repairs)


def test_model_filler_cast_limited_to_episode_cast():
    def model(**_k):
        return {"panels": [], "fillers": [
            {"after": f"p{i}", "cast": ["Kensei", "Teknium"], "action": "a glance", "shot": "close", "angle": "low"}
            for i in (2, 4, 6, 8, 10, 11)]}
    t = direct(IR, story_text="", complete_json=model)
    assert t.fillers and all(set(f.cast) <= {"Kensei"} for f in t.fillers)


def test_layout_solo_roles_get_their_own_row():
    sizes = [(1536, 1024)] * 6
    rows = layout_rows(sizes, ["setup", "insert", "filler", "climax", "filler", "win"])
    assert rows[0] == [0] and [3] in rows and rows[-1] == [5]
    assert [1, 2] in rows


def test_compose_pages_breaks_long_chapters_into_pages():
    panels = [Image.new("RGB", (1536, 1024), "grey") for _ in range(20)]
    roles = (["setup"] + ["insert", "filler"] * 9 + ["win"])
    pages = compose_pages(panels, roles, "Title", "To be continued", "credit")
    assert 3 <= len(pages) <= 5
    assert all(p.size[0] == pages[0].size[0] for p in pages)


def test_long_brief_spreads_roles_across_the_thread():
    from types import SimpleNamespace

    from canon.arcs import build_brief_arc

    turns = [SimpleNamespace(event_id=f"e{i}", actor="Sahil", text=f"turn number {i} said something") for i in range(14)]
    events = {f"e{i}": SimpleNamespace(ts=float(i)) for i in range(14)}
    brief = SimpleNamespace(turns=turns, goal="g", outcome="Fixed and merged.", thread_key="t")
    arc, beats = build_brief_arc(brief, events)
    order = [b.id for b in beats]
    positions = [order.index(arc.roles[r]) for r in ("setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win")]
    assert positions[0] == 0 and positions[-1] == 13
    assert positions == sorted(positions) and len(set(positions)) == 6


def test_chapter_brief_samples_beginning_to_end():
    from types import SimpleNamespace

    from canon.brief import _spread

    pairs = [(SimpleNamespace(ts=float(i)), f"text {i}") for i in range(40)]
    picked = _spread(pairs, 14)
    assert len(picked) == 14 and picked[0][1] == "text 0" and picked[-1][1] == "text 39"


def test_pipeline_names_resolve():
    """The kanban-thread arc path imports build_arc (latent NameError found 25/10/26)."""
    from adapters.hermes import pipeline

    assert callable(pipeline.build_arc)


def test_thin_chapter_gets_more_fillers_up_to_one_each():
    ir = {"logline": "x", "panels": [
        {"id": f"q{i}", "role": r, "caption": "c", "lines": [], "cast": ["Kensei"]}
        for i, r in enumerate(["setup", "insert", "hidden_problem", "diagnosis", "insert", "climax", "aftermath", "insert", "win"], 1)]}
    t = direct(ir, story_text="crash")
    assert len(ir["panels"]) + len(t.fillers) >= 16
    afters = [f.after for f in t.fillers]
    assert len(afters) == len(set(afters))  # at most one filler per story panel


def test_llm_writer_keys_each_insert_panel_separately():
    from canon.episode import LLMDialogueWriter

    class Fake:
        def complete_json(self, *, payload, **_k):
            return {"caption": f"Caption for {payload['facts']}.", "lines": []}

    writer = LLMDialogueWriter(Fake(), ["Sahil"])
    out = writer.write([
        {"role": "insert", "key": "insert-1", "fact_sentence": "one"},
        {"role": "insert", "key": "insert-2", "fact_sentence": "two"},
    ])
    assert out["insert-1"]["caption"] != out["insert-2"]["caption"]


def test_chapter_insert_panels_get_facts_and_evidence():
    """An insert spec reaching the writer carries the same sources as a role panel."""
    from types import SimpleNamespace

    from canon.arcs import build_brief_arc
    from canon.canon import Canon
    from canon.episode import plan_episode

    turns = [SimpleNamespace(event_id=f"e{i}", actor="Sahil", text=f"Sahil fixed bug number {i} in the parser") for i in range(10)]
    events = {f"e{i}": SimpleNamespace(ts=float(i)) for i in range(10)}
    brief = SimpleNamespace(turns=turns, goal="g", outcome="Fixed and merged.", thread_key="t")
    arc, beats = build_brief_arc(brief, events)
    seen = []

    class Spy:
        name = "spy"

        def write(self, panels):
            seen.extend(panels)
            return {}

    try:
        plan_episode(arc, beats, Canon(), format="chapter", writer=Spy(), brief=brief,
                     evidence={t.event_id: t.text for t in turns})
    except Exception:
        pass
    inserts = [p for p in seen if p["role"] == "insert"]
    assert inserts and all(p.get("evidence") and p.get("fact_sentence") for p in inserts)
    assert len({p["key"] for p in seen}) == len(seen)
