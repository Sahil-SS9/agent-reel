"""The series ledger and the idea deck: continuity, no repeats, a different look per chapter."""

from types import SimpleNamespace

from canon.ideas import combination_count, draw, load_deck
from canon.series import (
    Series,
    load,
    order_for_series,
    save,
    story_key,
    title_overlap,
)


def _cand(key: str, title: str, score: int = 5) -> SimpleNamespace:
    return SimpleNamespace(key=key, title=title, drama=score)


def test_a_told_story_is_never_told_again():
    series = Series()
    series.record(number=1, title="Four Lost, Four Gained", thread_key="t1", arc_id="a1", closed=True)
    assert series.already_told("Four Lost, Four Gained", "t9")  # same title
    assert series.already_told("Something else entirely", "t1")  # same thread
    assert not series.already_told("The Checker That Lied", "t2")


def test_a_near_duplicate_title_counts_as_told():
    series = Series()
    series.record(number=1, title="Four Lost and Four Gained", thread_key="t1", arc_id="a1")
    assert title_overlap("Four Lost, Four Gained", "Four Lost and Four Gained") >= 0.6
    assert "too close" in series.already_told("Four Lost Four Gained", "t2")


def test_the_open_thread_leads_the_next_chapter():
    series = Series()
    series.record(number=1, title="Chapter One", thread_key="open", arc_id="a1", cliffhanger=True)
    assert series.open_thread == "open"
    kept, dropped = order_for_series(
        [_cand("fresh", "A Brand New Story"), _cand("open", "Chapter One, part two")], series
    )
    assert [c.key for c in kept] == ["open", "fresh"]
    assert dropped == []


def test_repeats_are_dropped_with_a_reason():
    series = Series()
    series.record(number=1, title="Told Already", thread_key="t1", arc_id="a1", closed=True)
    kept, dropped = order_for_series([_cand("t1", "Told Already"), _cand("t2", "Fresh Story")], series)
    assert [c.key for c in kept] == ["t2"]
    assert dropped and dropped[0]["key"] == "t1"


def test_placeholder_titles_do_not_make_every_story_a_repeat():
    # A generic title identifies nothing; the thread key decides. Otherwise chapter 1's
    # "A session" would reject every later chapter.
    series = Series()
    series.record(number=1, title="A session", thread_key="t1", arc_id="a1", closed=True)
    assert series.already_told("A session", "t2") == ""
    assert series.already_told("A session", "t1")  # same thread still repeats


def test_a_closed_chapter_clears_the_open_thread():
    series = Series()
    series.record(number=1, title="A", thread_key="t1", arc_id="a1", cliffhanger=True)
    series.record(number=2, title="B", thread_key="t1", arc_id="a2", cliffhanger=False)
    assert series.open_thread == ""


def test_the_ledger_round_trips_through_disk(tmp_path):
    path = tmp_path / "series.json"
    series = Series()
    series.record(number=1, title="Saved Story", thread_key="t1", arc_id="a1", frame={"world": {"key": "w1"}})
    save(path, series)
    again = load(path)
    assert again.chapters == series.chapters
    assert again.next_number == 2
    assert again.told_keys() == {story_key("Saved Story", "t1")}


def test_a_missing_or_broken_ledger_is_not_an_error(tmp_path):
    assert load(tmp_path / "nope.json").chapters == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load(broken).chapters == []


def test_the_deck_is_huge_and_changes_every_chapter():
    deck = load_deck()
    assert combination_count(deck) > 100_000
    one = draw("Sahil", 1, deck=deck)
    two = draw("Sahil", 2, deck=deck)
    other_user = draw("Someone Else", 1, deck=deck)
    assert one != two
    assert one != other_user
    # reproducible for the same chapter
    assert draw("Sahil", 1, deck=deck) == one


def test_the_draw_avoids_what_the_last_chapters_used():
    deck = load_deck()
    first = draw("Sahil", 1, deck=deck)
    avoid = {"worlds": [first["world"]["key"]], "villains": [first["villain"]["key"]]}
    for chapter in range(2, 8):
        frame = draw("Sahil", chapter, deck=deck, avoid=avoid)
        assert frame["world"]["key"] != first["world"]["key"]
        assert frame["villain"]["key"] != first["villain"]["key"]


def test_the_deck_has_at_least_fifty_of_everything_and_no_duplicate_keys():
    deck = load_deck()
    for section, items in deck.items():
        assert len(items) >= 50, f"{section} has only {len(items)}"
        keys = [item["key"] for item in items]
        assert len(keys) == len(set(keys)), f"{section} has duplicate keys"
        assert all(item["label"].strip() for item in items), f"{section} has an empty label"


def test_every_section_is_actually_reachable_across_many_chapters():
    deck = load_deck()
    seen = {section: set() for section in deck}
    for chapter in range(1, 60):
        frame = draw("Sahil", chapter, deck=deck)
        for section in deck:
            key = section[:-1] if section.endswith("s") else section
            seen[section].add(frame[key]["key"])
    for section, keys in seen.items():
        assert len(keys) > 20, f"{section}: only {len(keys)} distinct values over 59 chapters"
