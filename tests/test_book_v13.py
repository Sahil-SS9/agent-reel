"""V13 (25/10/26): the monthly comic book PDF."""

import json
import time

import pytest
from PIL import Image

from canon.book import build_book, find_episodes, in_month


def _render(folder, title, when, pages=2):
    folder.mkdir(parents=True)
    for i in range(1, pages + 1):
        Image.new("RGB", (800, 1100), "grey").save(folder / f"page-{i}.jpg")
    Image.new("RGB", (400, 300), "red").save(folder / "panel-1.jpg")
    (folder / "sidecar.json").write_text(json.dumps({"title": title, "episode_time": when, "style": "anime"}))


def test_book_collects_month_in_date_order(tmp_path):
    oct1 = time.mktime((2026, 10, 3, 12, 0, 0, 0, 0, -1))
    oct2 = time.mktime((2026, 10, 20, 12, 0, 0, 0, 0, -1))
    sep = time.mktime((2026, 9, 20, 12, 0, 0, 0, 0, -1))
    _render(tmp_path / "b", "Second", oct2)
    _render(tmp_path / "a", "First", oct1, pages=3)
    _render(tmp_path / "c", "September", sep)
    episodes = in_month(find_episodes([tmp_path]), "2026-10")
    assert [e.title for e in episodes] == ["First", "Second"]
    report = build_book(episodes, tmp_path / "book.pdf", title="Scrollback Reel", subtitle="October 2026")
    assert report["pages"] == 2 + 3 + 2
    assert (tmp_path / "book.pdf").read_bytes()[:4] == b"%PDF"


def test_book_with_no_episodes_refuses(tmp_path):
    with pytest.raises(ValueError):
        build_book([], tmp_path / "x.pdf", title="t", subtitle="s")
