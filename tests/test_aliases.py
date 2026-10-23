"""Round 3 item 3: redacted terms become stable fictional aliases, never markers."""

from __future__ import annotations

import json
import os
import stat

from canon.aliases import AliasBook, apply_to_ir, masks_in
from canon.episode import EpisodeIR, Line, Panel


def book(tmp_path) -> AliasBook:
    return AliasBook.load(tmp_path / "state" / "aliases.json")


def test_a_mask_becomes_a_readable_alias(tmp_path):
    b = book(tmp_path)
    text = b.resolve("Fix the [REDACTED:project_name#ab12cd] slice")
    assert "[REDACTED" not in text
    assert text.startswith("Fix the Project ")


def test_the_same_value_gets_the_same_alias_every_time(tmp_path):
    b = book(tmp_path)
    first = b.resolve("[REDACTED:project_name#ab12cd]")
    second = b.resolve("[REDACTED:project_name#ab12cd]")
    assert first == second


def test_different_values_get_different_aliases(tmp_path):
    b = book(tmp_path)
    one = b.resolve("[REDACTED:project_name#aaaaaa]")
    two = b.resolve("[REDACTED:project_name#bbbbbb]")
    assert one != two, "two projects must not become the same name"


def test_aliases_persist_across_books(tmp_path):
    path = tmp_path / "state" / "aliases.json"
    first = AliasBook.load(path)
    alias = first.resolve("[REDACTED:client_name#c0ffee]")
    first.save()

    second = AliasBook.load(path)
    assert second.resolve("[REDACTED:client_name#c0ffee]") == alias
    assert json.loads(path.read_text(encoding="utf-8"))


def test_the_book_is_private(tmp_path):
    path = tmp_path / "state" / "aliases.json"
    b = AliasBook.load(path)
    b.resolve("[REDACTED:person_name#123456]")
    b.save()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_non_name_categories_read_as_descriptions(tmp_path):
    from canon.aliases import DESCRIPTIVE

    b = book(tmp_path)
    for category in ("email", "path", "ip", "financial", "health"):
        text = b.resolve(f"contact [REDACTED:{category}#abcdef] now")
        assert "[REDACTED" not in text
        alias = text.split("contact ", 1)[1].rsplit(" now", 1)[0]
        assert alias in DESCRIPTIVE[category], f"{category}: {alias!r}"


def test_an_untagged_mask_still_resolves(tmp_path):
    b = book(tmp_path)
    assert "[REDACTED" not in b.resolve("see [REDACTED:secret]")


def test_apply_to_ir_clears_every_mask(tmp_path):
    panel = Panel(
        id="p1",
        role="setup",
        shot="wide",
        cast=("Sahil",),
        pose="at the desk",
        expression="calm",
        setting="the rig",
        caption="Sun 18 Oct · [REDACTED:project_name#ab12cd]",
        lines=(Line("Sahil", "the [REDACTED:project_name#ab12cd] slice", ("ev_1",)),),
    )
    ir = EpisodeIR(
        episode_id="ep",
        season=1,
        number=1,
        format="strip",
        format_hints=("6-panel grid",),
        arc_ids=("arc",),
        logline="[REDACTED:project_name#ab12cd]: the week",
        panels=(panel,),
        writer="llm",
    )
    clean = apply_to_ir(ir, book(tmp_path))
    blob = json.dumps(clean.as_dict())
    assert "[REDACTED" not in blob
    assert masks_in(blob) == []
