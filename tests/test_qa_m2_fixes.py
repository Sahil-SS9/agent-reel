"""Quan's M2 review (QA-REVIEW-M2.md, 25/10/26): regression tests per finding."""

from types import SimpleNamespace

from canon.grounding import ClaimGate, check_claims, extract_claims


class Accepting:
    """A judge that accepts everything: only deterministic rules can refuse."""

    def __init__(self):
        self.calls = 0

    def complete_json(self, **_k):
        self.calls += 1
        return {"supported": True, "unbacked": []}


# QAR-M2-08 ------------------------------------------------------------------------
def test_meaning_mode_refuses_unknown_initial_names_and_written_numbers_without_the_judge():
    judge = Accepting()
    gate = ClaimGate(judge, cast=("Kensei", "Sahil"), meaning=True)
    assert not gate.check("Priya fixed the parser.", "Kensei fixed the parser.", layer="caption").supported
    assert not gate.check("Nine runs passed.", "8 runs passed and the report is written.", layer="caption").supported
    assert judge.calls == 0
    assert gate.check("Eight runs passed.", "8 runs passed.", layer="caption").supported
    assert not check_claims("Nine runs passed.", "eight runs passed").unbacked == ()


# QAR-M2-09 ------------------------------------------------------------------------
def test_actor_binding_needs_agency_not_co_occurrence():
    judge = Accepting()
    gate = ClaimGate(judge, cast=("Kensei", "Octacon"), meaning=True)
    evidence = "Kensei watched while Octacon fixed the release."
    assert not gate.check("Kensei fixed the release.", evidence, layer="caption").supported
    assert gate.check("Octacon fixed the release.", evidence, layer="caption").supported
    no_model = ClaimGate(None, cast=("Kensei", "Octacon"))
    assert not no_model.check("Kensei fixed the release.", evidence, layer="caption").supported


# QAR-M2-10 ------------------------------------------------------------------------
def test_no_model_caption_outcomes_fail_closed_unless_verbatim():
    gate = ClaimGate(None, cast=("Kensei", "Sahil"))
    reversed_evidence = "Sahil passed and Kensei failed."
    assert not gate.check("Kensei passed and Sahil failed.", reversed_evidence, layer="caption").supported
    assert gate.check("Sahil passed and Kensei failed.", reversed_evidence, layer="caption").supported


# QAR-M2-01 ------------------------------------------------------------------------
def _plan(lines, evidence, actors):
    from canon.arcs import build_brief_arc
    from canon.canon import Canon
    from canon.episode import plan_episode

    turns = [SimpleNamespace(event_id=e, actor=a, text=evidence[e]) for e, a in actors.items()]
    events = {e: SimpleNamespace(ts=float(i)) for i, e in enumerate(actors)}
    brief = SimpleNamespace(turns=turns, goal="g", outcome="Still running, about half done.", thread_key="t")
    arc, beats = build_brief_arc(brief, events)

    class Writer:
        name = "fake"

        def write(self, panels):
            return {p.get("key", p["role"]): {"caption": "", "lines": lines.get(p["role"], [])} for p in panels}

    try:
        ir = plan_episode(arc, beats, Canon(), writer=Writer(), grounder=ClaimGate(Accepting(), cast=("Sahil", "Kensei", "Quan")),
                          evidence=evidence, brief=brief, actors_by_event=actors, hero="Sahil",
                          cast_map={"default": "Kensei", "owner": "Sahil", "quan": "Quan"})
    except Exception as exc:  # noqa: BLE001 - surface why, so a refusal never passes a test vacuously
        raise AssertionError(f"episode refused: {exc}") from exc
    return [l for p in ir.panels for l in p.lines]


CONTROL = ["Kensei", "Nothing pushed, nothing running."]


EVIDENCE = {
    "e1": "Sahil: the session broke, please review it and check the background runs.",
    "e2": "Kensei: the nine-run set finished cleanly. Quan will re-check the results tomorrow.",
    "e3": "Kensei: the checker is broken for this repo; the code itself is fine.",
    "e4": "Kensei: corrections are ready for re-check, not accepted yet.",
    "e5": "Sahil: simpler please, and write the reply.",
    "e6": "Kensei: nothing pushed, nothing running.",
}
ACTORS = {"e1": "Sahil", "e2": "Kensei", "e3": "Kensei", "e4": "Kensei", "e5": "Sahil", "e6": "Kensei"}


def test_a_mentioned_bystander_cannot_speak_claims():
    lines = _plan({"hidden_problem": [["Quan", "The nine-run set finished cleanly."], CONTROL]}, EVIDENCE, ACTORS)
    assert any(l.text == CONTROL[1] for l in lines)  # the gate let a supported line through
    assert all(l.speaker != "Quan" for l in lines)


def test_a_line_cites_the_event_that_states_it():
    lines = _plan({"setup": [["Kensei", "The checker is broken for this repo, not the code."]], "win": [CONTROL]}, EVIDENCE, ACTORS)
    checker = [l for l in lines if "checker" in l.text]
    assert checker and checker[0].source_event_ids[0] == "e3"


def test_a_comical_unsupported_line_is_dropped():
    lines = _plan({"win": [["Kensei", "Brilliant: Octacon deleted the whole database. Twice!"], CONTROL]}, EVIDENCE, ACTORS)
    assert any(l.text == CONTROL[1] for l in lines)
    assert not any("database" in l.text for l in lines)


def test_a_statement_without_claim_tokens_cites_the_event_that_states_it():
    # Takeover finding on d7bc116: lines with no extractable claim token kept the panel's
    # ids. "Corrections are ready for re-check" has no number/name/outcome token.
    assert not extract_claims("Corrections are ready for a re-check.")
    lines = _plan({"setup": [["Kensei", "Corrections are ready for a re-check."]], "win": [CONTROL]}, EVIDENCE, ACTORS)
    hit = [l for l in lines if "Corrections" in l.text]
    assert hit and hit[0].source_event_ids == ("e4",)


def test_a_statement_no_event_states_is_dropped_even_by_an_accepting_judge():
    lines = _plan({"win": [["Kensei", "The rocket garden sailed over the moonlit harbour."], CONTROL]}, EVIDENCE, ACTORS)
    assert any(l.text == CONTROL[1] for l in lines)
    assert not any("rocket" in l.text for l in lines)


def test_a_question_or_reaction_is_not_treated_as_a_statement():
    from canon.episode import _states_something

    assert not _states_something("What's that one? Another disaster I should know about?")
    assert not _states_something("Understood.")
    assert _states_something("Every test passes on both databases. Not one failure.")



# QAR-M2-07 ------------------------------------------------------------------------
def test_page_layout_keeps_lettering_readable():
    from PIL import Image

    from canon.export import MAX_PER_ROW, compose_pages, layout_rows
    from canon.letterer import letter_panel

    sizes = [(1024, 1024)] * 6
    rows = layout_rows(sizes, ["insert"] * 6)
    assert max(len(r) for r in rows) <= MAX_PER_ROW
    panel = Image.new("RGB", (1536, 1024), "white")
    base, rep1 = letter_panel(panel, heads={"Sahil": [0.4, 0.5, 0.5, 0.7]}, free=[[0.05, 0.02, 0.95, 0.3]], lines=[("Sahil", "Simpler, please.")])
    big, rep2 = letter_panel(panel, heads={"Sahil": [0.4, 0.5, 0.5, 0.7]}, free=[[0.05, 0.02, 0.95, 0.3]], lines=[("Sahil", "Simpler, please.")], font_scale=1.4)
    b1, b2 = rep1.balloons[0]["box"], rep2.balloons[0]["box"]
    assert (b2[3] - b2[1]) * (b2[2] - b2[0]) > (b1[3] - b1[1]) * (b1[2] - b1[0])
    from canon.export import MIN_PANEL_SHARE, PAGE_WIDTH, _row_geometry

    for kind in ([(1024, 1024)] * 6, [(1024, 1536)] * 6, [(1536, 1024)] * 6):
        for row in layout_rows(kind, ["insert"] * 6):
            _h, widths = _row_geometry(row, kind, PAGE_WIDTH, PAGE_WIDTH // 100)
            assert min(widths) >= MIN_PANEL_SHARE * PAGE_WIDTH * 0.8, (kind[0], widths)
    assert compose_pages([panel] * 6, ["insert"] * 6, "T")
