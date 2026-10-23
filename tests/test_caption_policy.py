"""R4-F2: captions paraphrase in at most 20 words and never quote the owner."""

from __future__ import annotations

from canon.caption import (
    MAX_CAPTION_WORDS,
    MAX_OWNER_QUOTE_WORDS,
    caption_problem,
    longest_common_run,
    trim_caption,
)

OWNER = "I want you to look at lcm-x and look at our Severian Memory system and tell me what we are failing on"


def test_a_short_paraphrase_is_fine():
    assert caption_problem("Sahil asks for a true benchmark of both memory systems.", owner_texts=[OWNER]) == ""


def test_a_long_caption_is_refused():
    long_caption = " ".join(["word"] * (MAX_CAPTION_WORDS + 1))
    assert "over 20 words" in caption_problem(long_caption)


def test_quoting_the_owner_over_eight_words_is_refused():
    quote = "look at lcm-x and look at our Severian Memory system"
    assert longest_common_run(quote, OWNER) > MAX_OWNER_QUOTE_WORDS
    assert "quotes the owner" in caption_problem(quote, owner_texts=[OWNER])


def test_a_short_owner_quote_is_allowed():
    assert caption_problem("Sahil: our Severian Memory system.", owner_texts=[OWNER]) == ""


def test_provenance_is_refused():
    assert caption_problem('event: kanban.task.status gave_up octacon') == "provenance"


def test_trim_keeps_a_sentence_under_the_cap():
    trimmed = trim_caption(" ".join(["word"] * 30))
    assert trimmed.endswith(".")
    assert len(trimmed.split()) <= MAX_CAPTION_WORDS


def test_trim_leaves_a_short_caption_alone():
    assert trim_caption("Sahil asks for a true benchmark.") == "Sahil asks for a true benchmark."
