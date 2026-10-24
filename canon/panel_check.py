"""Per-panel auto-check (M2 P4). Harness-free: the vision call is injected.

One vision question per panel returns:
- **On-model check** for each scripted character (face, hair, outfit, colours).
- **Count of people** drawn who are not in the script. Bake-off r2 saw the model add Sahil to panels he wasn't in.
- **Text check**: whether any lettering appears in the art.
- **Normalised head boxes** for each scripted character. The letterer aims tails at these.
- **Free regions** where balloons may go, and **keep-out boxes** for key objects.

A panel fails when a character is off-model, when anyone unscripted is drawn, or when text appears. Failed panels are regenerated up to N times by the caller; if they still fail, the episode is flagged, never shipped quietly.

A head box covering more than ``COARSE_HEAD_AREA`` of the frame is too coarse to aim a tail at. Bake-off r2 found 3 of 12 boxes like this, so those are re-asked tightly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

COARSE_HEAD_AREA = 0.06

CHECK_QUESTION = (
    "You are checking one comic panel before lettering. Answer with JSON only, no prose.\n"
    "Scripted characters, left to right as staged: {cast}.\n"
    "Reference descriptions: {descriptions}.\n"
    "Return: {{\"on_model\": {{NAME: true|false}}, \"extra_people\": INT, "
    "\"text_in_image\": true|false, \"heads\": {{NAME: [x0, y0, x1, y1]}}, "
    "\"free\": [[x0, y0, x1, y1], ...], \"keep_out\": [[x0, y0, x1, y1], ...]}}.\n"
    "All boxes are fractions of width and height (0..1). heads = the tight box around "
    "each scripted character's head and face only. free = empty background where speech "
    "balloons can go without covering faces or key objects. keep_out = key objects or "
    "action that must stay visible. extra_people = people or characters drawn who are not "
    "in the scripted list. text_in_image = READABLE words or letters, speech bubbles or "
    "captions drawn in the art; tiny unreadable interface or code squiggles on screens do not "
    "count."
)

LETTER_QUESTION = (
    "Answer with JSON only. This comic panel has speech balloons added. For each balloon, "
    "say whether its tail points at the face or head of the character named here as its "
    "speaker: {speakers}. Return {{\"misses\": [SPEAKER, ...]}} listing every speaker whose "
    "balloon tail does NOT point at them, or an empty list."
)

TIGHT_QUESTION = (
    "Answer with JSON only. Give the TIGHT box around the head and face of {name} in this "
    "comic panel, as fractions of width and height: {{\"head\": [x0, y0, x1, y1]}}. "
    "The box must cover the head only, not the body."
)


@dataclass
class PanelCheck:
    panel_id: str
    on_model: dict[str, bool] = field(default_factory=dict)
    extra_people: int = 0
    text_in_image: bool = False
    heads: dict[str, list[float]] = field(default_factory=dict)
    free: list[list[float]] = field(default_factory=list)
    keep_out: list[list[float]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "passed": self.passed,
            "on_model": self.on_model,
            "extra_people": self.extra_people,
            "text_in_image": self.text_in_image,
            "heads": self.heads,
            "free": self.free,
            "keep_out": self.keep_out,
            "problems": self.problems,
        }


def _box(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if x1 - x0 <= 0.005 or y1 - y0 <= 0.005:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def interpret(
    panel_id: str,
    cast: Sequence[str],
    answer: Mapping[str, Any],
    *,
    tighten: Callable[[str], Any] | None = None,
    require_heads: Sequence[str] | None = None,
) -> PanelCheck:
    """``require_heads``: who needs a head box (the speakers); default: the whole cast."""
    check = PanelCheck(panel_id=panel_id)
    raw_on_model = answer.get("on_model")
    on_model: Mapping[str, Any] = raw_on_model if isinstance(raw_on_model, dict) else {}
    lowered = {str(k).lower(): v for k, v in on_model.items()}
    for name in cast:
        verdict = lowered.get(name.lower())
        check.on_model[name] = bool(verdict)
        if verdict is not True:
            check.problems.append(f"{name} is off-model or not found")
    try:
        check.extra_people = int(answer.get("extra_people") or 0)
    except (TypeError, ValueError):
        check.extra_people = 1
        check.problems.append("could not read the extra-people count")
    if check.extra_people > 0:
        check.problems.append(f"{check.extra_people} unscripted people drawn")
    check.text_in_image = bool(answer.get("text_in_image"))
    if check.text_in_image:
        check.problems.append("text drawn in the art")

    raw_heads = answer.get("heads")
    heads: Mapping[str, Any] = raw_heads if isinstance(raw_heads, dict) else {}
    heads_lower = {str(k).lower(): v for k, v in heads.items()}
    needed = {n.lower() for n in (require_heads if require_heads is not None else cast)}
    for name in cast:
        box = _box(heads_lower.get(name.lower()))
        if box is None and name.lower() not in needed:
            continue
        if box is not None and area(box) > COARSE_HEAD_AREA and tighten is not None:
            tight = tighten(name)
            tight_box = _box((tight or {}).get("head")) if isinstance(tight, dict) else None
            if tight_box is not None:
                box = tight_box
        if box is None:
            check.problems.append(f"no head box for {name}")
            continue
        check.heads[name] = box
    check.free = [b for b in (_box(v) for v in answer.get("free") or []) if b]
    check.keep_out = [b for b in (_box(v) for v in answer.get("keep_out") or []) if b]
    if not check.free:
        check.problems.append("no free space for balloons reported")
    return check


def check_question(cast: Sequence[str], descriptions: Mapping[str, str]) -> str:
    described = "; ".join(f"{name}: {descriptions.get(name, 'see reference')}" for name in cast) or "none"
    return CHECK_QUESTION.format(cast=", ".join(cast) or "none", descriptions=described)
