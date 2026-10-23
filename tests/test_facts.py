"""Round 6: a brief becomes atomic facts captions and lines can be judged against."""

from __future__ import annotations

from canon.brief import build_brief
from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER, build_event
from canon.facts import build_facts, fact_numbers, facts_text, outcome_facts
from canon.gate import seal


def msg(kind, text, ts, role, actor=None):
    event = build_event(
        source="session", kind=kind, ts=ts, profile="default",
        actor=actor or ("owner" if role == "user" else "denji"),
        subject="s1", payload={"text": text, "role": role, "session_id": "s1"},
        store="main", table="messages", pk=f"s1-{ts}",
    )
    return seal(event, event.payload)


def rows():
    return [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against LCM-X properly", 1.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "assistant"),
        msg(KIND_MESSAGE_USER, "The numbers must be comparable and honest", 3.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Scored the long-context set and wrote the results table", 4.0, "assistant"),
        msg(
            KIND_MESSAGE_ASSISTANT,
            "Severian 87.3 vs LCM-X 79.5 on LoCoMo; a tie on BEAM; LongMemEval still running",
            5.0,
            "assistant",
        ),
    ]


def facts():
    events = rows()
    brief = build_brief("s1", "session", events)
    return build_facts(brief, {row.id: row for row in events}, display={"owner": "Sahil", "denji": "Denji"})


def test_the_goal_becomes_the_owner_wants_a_thing():
    goal = facts()[0]
    assert goal.kind == "goal"
    assert goal.actor == "Sahil"
    assert goal.sentence.startswith("Sahil wants")
    assert "asked" not in goal.sentence


def test_turns_become_actor_action_object_facts():
    turns = [fact for fact in facts() if fact.kind == "turn"]
    assert turns
    for fact in turns:
        assert fact.actor and fact.action
        # no template filler survives into a fact
        assert not fact.sentence.startswith(("Worked on", "Reported"))


def test_the_outcome_yields_one_fact_per_clause_with_its_numbers():
    outcomes = outcome_facts(facts())
    assert len(outcomes) >= 3
    text = " ".join(fact.sentence for fact in outcomes)
    assert "87.3" in text and "79.5" in text
    assert "BEAM" in text


def test_every_fact_sentence_is_a_sentence():
    for fact in facts():
        sentence = fact.sentence
        assert sentence.endswith(".")
        assert sentence[0].isupper()
        assert len(sentence.split()) <= 20


def test_the_fact_list_is_short_and_clean():
    text = facts_text(facts())
    assert "asked for" not in text.lower()
    assert "worked on" not in text.lower()
    assert "event:" not in text


def test_numbers_are_collected():
    numbers = fact_numbers(facts())
    assert "87.3" in numbers
    assert "79.5" in numbers
