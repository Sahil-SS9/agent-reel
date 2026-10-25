"""V6-V8 (25/10/26): plain-English story layer, meaning-level truth check, voices."""

from canon.episode import LLMDialogueWriter
from canon.grounding import ClaimGate
from canon.story import behind_the_panels, edit_script, jargon_problem, write_synopsis


def test_jargon_detector():
    assert jargon_problem("verify failed with exit 127")
    assert jargon_problem("superseded by d610509 runs")
    assert jargon_problem("see adapters/hermes/pipeline.py")
    assert jargon_problem("task t_ec1754fc is blocked")
    assert jargon_problem("min_strip_panels was lowered")
    assert not jargon_problem("Eight attempts, and not one cleared the bar.")
    assert not jargon_problem("Severian beat LCM-X 87.3 to 79.5.")


class Judge:
    """Accepts everything; records what it was asked."""

    def __init__(self):
        self.calls = []

    def complete_json(self, *, prompt, payload, **_k):
        self.calls.append((prompt, payload))
        return {"supported": True, "unbacked": []}


def test_meaning_mode_drops_vocabulary_floor_but_keeps_numbers_and_names():
    judge = Judge()
    strict = ClaimGate(judge, cast=("Kensei",))
    meaning = ClaimGate(judge, cast=("Kensei",), meaning=True)
    evidence = "The first verify attempt failed with exit 127 because the probe worktree lacked hermes."
    plain = "The first check failed because the test copy was missing a tool."
    assert not strict.check(plain, evidence, layer="caption").supported  # floor refuses
    assert meaning.check(plain, evidence, layer="caption").supported
    assert "plain English" in judge.calls[-1][0]
    # deterministic rules still apply before any model call
    assert not meaning.check("It failed 3 times.", evidence, layer="caption").supported
    assert not meaning.check("Kensei broke the test copy.", evidence, layer="caption").supported


def test_meaning_mode_without_model_still_fails_closed():
    gate = ClaimGate(None, meaning=True)
    assert not gate.check("The check failed because a tool was missing.", "verify exit 127 lacked hermes", layer="caption").supported


def test_synopsis_sentences_are_gated_and_jargon_refused():
    def model(**_k):
        return {"logline": "Kensei hunts a broken checker.", "want": "Sahil wants it shipped.",
                "stakes": "Exit 127 blocks everything.", "turn": "", "ending": "Nothing passes."}

    class Gate:
        def check(self, line, evidence, layer="caption"):
            from types import SimpleNamespace
            return SimpleNamespace(supported="shipped" not in line, reason="not entailed")

    syn = write_synopsis(model, title="t", facts_text="f", brief_text="b", gate=Gate())
    assert syn.fields["logline"] and syn.fields["ending"]
    assert "want" in syn.refused and "stakes" in syn.refused
    assert "Exit" not in syn.text()


def test_editor_parses_and_clamps():
    out = edit_script(lambda **_k: {"score": 9, "problems": [{"panel": "x-p2", "issue": "jargon"}, "junk"]},
                      [{"id": "x-p1", "role": "setup", "caption": "c", "lines": []}], synopsis="s")
    assert out["score"] == 5 and out["problems"] == [{"panel": "x-p2", "issue": "jargon"}]
    assert edit_script(None, [], synopsis="")["score"] == 0


def test_story_writer_sends_synopsis_voices_and_notes_and_drops_jargon():
    seen = []

    class Model:
        def complete_json(self, *, prompt, payload, **_k):
            seen.append((prompt, payload))
            return {"caption": "Commit d610509 replaced them.", "lines": [
                {"speaker": "Kensei", "text": "Halfway step. The final runs replace it."},
                {"speaker": "Sahil", "text": "And exit 127?"}]}

    writer = LLMDialogueWriter(Model(), ["Kensei", "Sahil"], story={
        "synopsis": "S", "voices": {"Kensei": "calm", "narrator": "punchy"}, "jobs": {"insert": "move"},
        "notes": {"p2": "too technical"}})
    out = writer.write([
        {"role": "setup", "key": "setup", "actors": ["Kensei", "Sahil"]},
        {"role": "insert", "key": "insert-1", "actors": ["Kensei", "Sahil"]},
    ])
    prompt, payload = seen[1]
    assert "general reader" in prompt and payload["synopsis"] == "S"
    assert payload["panel_job"] == "move" and payload["editor_note"] == "too technical"
    assert payload["voices"]["Kensei"] == "calm" and "setting" not in payload
    assert "editor_note" not in seen[0][1]
    assert out["insert-1"]["caption"] == ""  # hash caption dropped
    assert [s for s, _ in out["insert-1"]["lines"]] == ["Kensei"]  # exit-code line dropped
    assert writer.jargon_dropped == 4


def test_m1_writer_prompt_unchanged_without_story():
    seen = []

    class Model:
        def complete_json(self, *, prompt, payload, **_k):
            seen.append(prompt)
            return {"caption": "A caption here.", "lines": []}

    LLMDialogueWriter(Model(), ["Kensei"]).write([{"role": "setup"}])
    assert seen[0] == LLMDialogueWriter.PROMPT


def test_behind_the_panels_lists_real_details():
    md = behind_the_panels([{"id": "a-p1", "role": "setup", "caption_source_event_ids": ["ev_1"]}],
                           {"a-p1": "verify failed with exit 127"})
    assert "exit 127" in md and "Panel 1" in md
