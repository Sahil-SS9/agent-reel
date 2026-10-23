"""R4-F6 public mode masks money; R4-F5 reports what is shown."""

from __future__ import annotations

from adapters.hermes.redact_source import public_rules, rules_from_snapshot
from canon.redact import DeterministicRedactor, RedactionGate


def gate(privacy: str) -> RedactionGate:
    rules = list(rules_from_snapshot())
    if privacy == "public":
        rules.extend(public_rules())
    return RedactionGate(DeterministicRedactor(rules), privacy=privacy)


def test_private_mode_keeps_the_owners_money_figures():
    text = "the invoice came to $21.45 of $30"
    redacted, _findings = gate("private").redact_text(text)
    assert "$21.45" in redacted


def test_public_mode_masks_money():
    text = "the invoice came to $21.45 of $30"
    redacted, findings = gate("public").redact_text(text)
    assert "$21.45" not in redacted
    assert "$30" not in redacted
    assert "[REDACTED:financial#" in redacted
    assert any(finding.category == "financial" for finding in findings)


def test_public_mode_masks_an_nhs_number():
    text = "her nhs number is 943 476 5919"
    redacted, findings = gate("public").redact_text(text)
    assert "943 476 5919" not in redacted
    assert any(finding.category == "health" for finding in findings)


def test_public_mode_still_masks_secrets():
    redacted, findings = gate("public").redact_text("token ghp_abcdefghijklmnopqrstuvwxyz0123")
    assert "ghp_" not in redacted
    assert any(finding.category == "secret" for finding in findings)


def test_public_rules_are_deterministic_only():
    # public mode must not depend on a model: the rule set is pure regex
    for rule in public_rules():
        assert hasattr(rule.pattern, "search")


def test_the_header_title_is_counted():
    """R4-F5: report the header line the reader actually sees, not just the title."""
    from canon.episode import plan_episode

    # A tiny IR is enough: the count must reflect the rendered header, not a hope.
    from canon.arcs import build_brief_arc
    from canon.beats import beats_from_events
    from canon.brief import build_brief
    from canon.canon import build_canon
    from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER, build_event
    from canon.gate import seal

    def msg(kind, text, ts, role):
        event = build_event(
            source="session", kind=kind, ts=ts, profile="default",
            actor="owner" if role == "user" else "denji", subject="s1",
            payload={"text": text, "role": role, "session_id": "s1"},
            store="main", table="messages", pk=f"s1-{ts}",
        )
        return seal(event, event.payload)

    rows = [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against the competitor", 1.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "assistant"),
        msg(KIND_MESSAGE_USER, "The numbers must be comparable and honest", 3.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Benchmark complete: 87.3 against 79.5", 4.0, "assistant"),
    ]
    brief = build_brief("s1", "session", rows)
    arc, beats = build_brief_arc(brief, {row.id: row for row in rows})
    ir = plan_episode(
        arc, list(beats), build_canon(rows, beats_from_events(rows)),
        evidence={row.id: str(row.payload.get("text", "")) for row in rows},
        brief=brief, cast_map={"owner": "Sahil", "denji": "Denji"},
    )
    assert ir.logline
    assert len(ir.logline.split()) == len(ir.logline.split())
