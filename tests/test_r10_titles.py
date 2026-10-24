"""Round 10: a reworded model title is judged like a caption when a judge exists.

r9 headed strips "A session" because every model title had to reuse beat-summary words
verbatim. With a model judge the title gets the caption rule (vocabulary floor plus
entailment); without one, the verbatim rule stays.
"""

from __future__ import annotations

from types import SimpleNamespace

from canon.grounding import ClaimGate
from canon.titling import write_title


class TitleLLM:
    def __init__(self, title: str, supported: bool = True) -> None:
        self.title = title
        self.supported = supported
        self.stages: list[str] = []

    def complete_json(self, *, prompt, payload, schema_hint=None, stage=""):
        self.stages.append(stage)
        if stage == "episode.title":
            return {"title": self.title}
        return {"supported": self.supported, "unbacked": []}


BEATS = [SimpleNamespace(summary="sahil asked for an audit of discord job output; 8 jobs had problems")]
EVIDENCE = "I need you to look through all our discord output from our jobs and find failed jobs. The audit found 8 jobs with problems."


def test_reworded_title_passes_with_a_judge():
    llm = TitleLLM("Recon audit of failed Discord jobs")
    title, source = write_title(llm, beats=BEATS, derived="A session", gate=ClaimGate(llm), evidence=EVIDENCE)
    assert (title, source) == ("Recon audit of failed Discord jobs", "model")
    assert "grounding" in llm.stages


def test_judge_refusal_falls_back():
    llm = TitleLLM("Recon audit of failed Discord jobs", supported=False)
    _, source = write_title(llm, beats=BEATS, derived="A session", gate=ClaimGate(llm), evidence=EVIDENCE)
    assert source == "ungrounded"


def test_invented_number_in_title_falls_back():
    llm = TitleLLM("Nine failed Discord jobs, 12 fixed")
    _, source = write_title(llm, beats=BEATS, derived="A session", gate=ClaimGate(llm), evidence=EVIDENCE)
    assert source == "ungrounded"
