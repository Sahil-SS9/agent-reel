"""M2 P5: the letterer never covers a face, keeps reading order, aims tails at faces."""

from __future__ import annotations

from PIL import Image

from canon.letterer import BODY_FONT, TITLE_FONT, letter_panel


def _blank(w=1536, h=1024):
    return Image.new("RGB", (w, h), (90, 120, 160))


HEADS = {"Sahil": [0.25, 0.40, 0.35, 0.58], "Kensei": [0.70, 0.30, 0.82, 0.50]}
FREE = [[0.05, 0.01, 0.95, 0.27]]


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def test_fonts_are_present_and_licensed():
    assert BODY_FONT.is_file() and TITLE_FONT.is_file()
    assert (BODY_FONT.parent / "OFL.txt").is_file()


def test_balloons_avoid_faces_and_follow_reading_order():
    im, report = letter_panel(
        _blank(), heads=HEADS, free=FREE, caption="Sahil asks for a read-only audit.",
        lines=[("Sahil", "Look, don't touch."), ("Kensei", "Read-only. Understood.")],
    )
    assert report.complete, report.unplaced
    w, h = im.size
    for balloon in report.balloons:
        for head in HEADS.values():
            px = [head[0] * w, head[1] * h, head[2] * w, head[3] * h]
            assert _overlap(balloon["box"], px) == 0
    first, second = report.balloons
    assert second["box"][1] >= first["box"][1] + 30 or second["box"][0] >= first["box"][2] - 20
    assert report.caption_box is not None


def test_tail_points_towards_the_speaker():
    _, report = letter_panel(_blank(), heads=HEADS, free=FREE, lines=[("Kensei", "On it.")])
    balloon = report.balloons[0]
    w, h = 1536, 1024
    head = HEADS["Kensei"]
    head_centre_x = (head[0] + head[2]) / 2 * w
    box_centre_x = (balloon["box"][0] + balloon["box"][2]) / 2
    assert abs(balloon["tip"][0] - head_centre_x) < abs(box_centre_x - head_centre_x) + 1


def test_offscreen_speaker_gets_a_comms_balloon():
    _, report = letter_panel(_blank(), heads=HEADS, free=FREE, lines=[("Octacon", "Patch ready.")])
    assert report.balloons[0]["comms"] is True


def test_no_space_is_reported_not_dropped():
    full = {"A": [0.0, 0.0, 1.0, 1.0]}
    _, report = letter_panel(_blank(400, 300), heads=full, free=[], lines=[("A", "Hello there friend.")])
    assert report.unplaced == ["A: Hello there friend."]


def test_scales_to_small_images():
    im, report = letter_panel(_blank(768, 512), heads=HEADS, free=FREE, lines=[("Sahil", "Smaller panel.")])
    assert report.complete and im.size == (768, 512)


def test_a_balloon_tail_never_crosses_another_balloon():
    """26/10/26: crossing tails read as a layout mistake and can clip words."""
    from PIL import Image

    from canon.letterer import letter_panel

    image = Image.new("RGB", (900, 600), "white")
    panel = {
        "id": "p1", "role": "climax", "setting": "a roof", "cast": ["Sahil", "Kensei"],
        "lines": [
            {"speaker": "Sahil", "text": "First line that has to be placed somewhere."},
            {"speaker": "Kensei", "text": "Second line, aimed back at the other speaker."},
        ],
    }
    heads = {"Sahil": [0.1, 0.5, 0.25, 0.75], "Kensei": [0.7, 0.5, 0.85, 0.75]}
    lettered, report = letter_panel(
        image, heads=heads, free=[], caption="", lines=[(l["speaker"], l["text"]) for l in panel["lines"]],
    )
    boxes = [b["box"] for b in report.balloons]
    assert len(boxes) == 2
    for balloon in report.balloons:
        tip = balloon["tip"]
        for box in boxes:
            if [int(v) for v in box] == balloon["box"]:
                continue
            inside = box[0] <= tip[0] <= box[2] and box[1] <= tip[1] <= box[3]
            assert not inside, f"tail tip {tip} lands inside another balloon {box}"
