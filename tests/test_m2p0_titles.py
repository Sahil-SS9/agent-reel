"""M2 P0: a refused first title option falls through to the next one."""

from types import SimpleNamespace

from canon.grounding import ClaimGate
from canon.titling import write_title


class Options:
    def __init__(self, titles):
        self.titles = titles

    def complete_json(self, *, prompt, payload, schema_hint=None, stage=""):
        if stage == "episode.title":
            return {"titles": self.titles}
        return {"supported": True, "unbacked": []}


BEATS = [SimpleNamespace(summary="the reviewer returned a partial verdict and the final test passed")]
EVIDENCE = "The reviewer returned a partial verdict. The final test passes."


def test_second_option_is_used_when_the_first_invents_a_name():
    llm = Options(["Evaluator Review Handoff Saga", "Partial verdict, final test passes"])
    title, source = write_title(llm, beats=BEATS, derived="A session", gate=ClaimGate(llm), evidence=EVIDENCE)
    assert (title, source) == ("Partial verdict, final test passes", "model")


def test_all_options_refused_falls_back():
    llm = Options(["Evaluator Review Handoff", "Grill And Bake-off"])
    _, source = write_title(llm, beats=BEATS, derived="A session", gate=ClaimGate(llm), evidence=EVIDENCE)
    assert source == "ungrounded"


def test_old_single_title_shape_still_works():
    class One(Options):
        def complete_json(self, *, prompt, payload, schema_hint=None, stage=""):
            if stage == "episode.title":
                return {"title": "Partial verdict, final test passes"}
            return {"supported": True, "unbacked": []}

    llm = One([])
    title, source = write_title(llm, beats=BEATS, derived="A session", gate=ClaimGate(llm), evidence=EVIDENCE)
    assert source == "model"


def test_lowercase_allow_only_caller_still_gets_the_actor_check():
    verdict = ClaimGate(None, allow=("sahil", "kensei")).check(
        "Kensei approved the release.", "Sahil approved the release.", layer="caption"
    )
    assert not verdict.supported
