"""Round 7: the two caption bypasses in plan_episode are closed.

The r6 audit found the composer's "Kensei worked on ..." sentences reaching the page
through a repair path (re-checked against raw evidence) and an empty-panel fallback.
Both now go through one policy helper whose only source is the panel's fact sentence.
"""

from __future__ import annotations

from canon.arcs import build_brief_arc
from canon.beats import beats_from_events
from canon.brief import build_brief
from canon.canon import build_canon
from canon.caption import caption_problem, compose_caption
from canon.episode import plan_episode
from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER, build_event
from canon.facts import build_facts, facts_text
from canon.gate import seal


def msg(kind, text, ts, role):
    event = build_event(
        source="session", kind=kind, ts=ts, profile="default",
        actor="owner" if role == "user" else "denji", subject="s1",
        payload={"text": text, "role": role, "session_id": "s1"},
        store="main", table="messages", pk=f"s1-{ts}",
    )
    return seal(event, event.payload)


def fixture():
    return [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against LCM-X properly", 1.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "assistant"),
        msg(KIND_MESSAGE_USER, "The numbers must be comparable and honest", 3.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Scored the long-context set and wrote the results table", 4.0, "assistant"),
        msg(KIND_MESSAGE_ASSISTANT, "Severian 87.3 vs LCM-X 79.5 on LoCoMo; a tie on BEAM; LongMemEval still running", 5.0, "assistant"),
    ]


def plan(*, facts=True):
    rows = fixture()
    by_id = {row.id: row for row in rows}
    brief = build_brief("s1", "session", rows)
    real = build_facts(brief, by_id, display={"owner": "Sahil", "denji": "Kensei"}, hero="Sahil")
    arc, beats = build_brief_arc(brief, by_id)
    structured = {row.id: compose_caption(row) for row in rows}  # composer output: the old trap
    class Captions:
        name = "captions"

        def write(self, panels):
            return {
                panel["role"]: {
                    "caption": str(panel.get("fact_sentence") or "").strip(),
                    "lines": [],
                }
                for panel in panels
            }

    return plan_episode(
        arc, list(beats), build_canon(rows, beats_from_events(rows)),
        evidence={row.id: str(row.payload.get("text", "")) for row in rows},
        brief=brief,
        facts=real if facts else (),
        facts_evidence=facts_text(real) if facts else "",
        structured_captions=structured,
        cast_map={"owner": "Sahil", "denji": "Kensei"},
        writer=Captions(),
    )


def test_a_caption_that_passes_against_the_facts_is_not_repaired():
    ir = plan()
    assert ir.grounding["captions_repaired"] == 0
    assert ir.grounding["captions_supported"] == ir.grounding["captions"]


def test_neither_fallback_can_emit_a_caption_problem_string():
    ir = plan()
    assert ir.panels
    for panel in ir.panels:
        if panel.caption:
            assert caption_problem(panel.caption, max_owner_quote=8) == ""


def test_the_strip_carries_no_template_panels():
    """The synth probe's symptom: composer verbs on the page. There are none."""
    ir = plan()
    captions = [panel.caption for panel in ir.panels if panel.caption]
    assert captions
    for caption in captions:
        assert "worked on" not in caption.lower()
        assert "asked for" not in caption.lower()
        assert not caption.lower().startswith("kensei reported")


def test_the_climax_states_the_benchmark_result():
    ir = plan()
    climax = [panel for panel in ir.panels if panel.role in {"climax", "win"}]
    text = " ".join(panel.caption for panel in climax)
    assert "87.3" in text and "79.5" in text


class RecordingGrounder:
    """Accepts fact evidence, rejects the raw evidence, and records every check.

    This is the affected-path proof the r7 audit asked for: the repair branch can only be
    reached if the grounder rejects the chosen caption, and the branch must re-check against
    the facts, never the raw event text.
    """

    def __init__(self, reject_text: str):
        self.reject_text = reject_text
        self.calls: list[tuple[str, str, str]] = []

    def check(self, text, evidence, *, layer="caption"):
        self.calls.append((text, evidence, layer))

        class Verdict:
            def __init__(self, supported, reason=""):
                self.supported = supported
                self.reason = reason

        if text.strip() == self.reject_text:
            return Verdict(False, "rejected by the recording grounder")
        return Verdict(True)

    def literal_caption(self, evidence):
        return ""


def test_a_rejected_caption_is_dropped_rather_than_repaired():
    """Round 8: there is no mechanical repair any more - a bad caption leaves silence."""
    rows = fixture()
    by_id = {row.id: row for row in rows}
    brief = build_brief("s1", "session", rows)
    facts = build_facts(brief, by_id, display={"owner": "Sahil", "denji": "Kensei"}, hero="Sahil")
    arc, beats = build_brief_arc(brief, by_id)
    offered = "The team benchmarked both systems carefully."
    grounder = RecordingGrounder(reject_text=offered)

    class Talker:
        name = "recording"

        def write(self, panels):
            return {panel["role"]: {"caption": offered, "lines": []} for panel in panels}

    ir = plan_episode(
        arc, list(beats), build_canon(rows, beats_from_events(rows)),
        evidence={row.id: str(row.payload.get("text", "")) for row in rows},
        brief=brief, facts=facts, facts_evidence=facts_text(facts),
        cast_map={"owner": "Sahil", "denji": "Kensei"},
        writer=Talker(), grounder=grounder,
    )
    assert ir.grounding["captions_repaired"] == 0
    assert offered not in {panel.caption for panel in ir.panels}
    caption_checks = [call for call in grounder.calls if call[2] == "caption"]
    assert caption_checks
    # the judge text is the fact list plus the panel's own evidence (round 8 union)
    for _text, evidence, _layer in caption_checks:
        assert facts_text(facts) in evidence
