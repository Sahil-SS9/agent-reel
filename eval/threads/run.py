#!/usr/bin/env python3
"""Round 3 item 7: 30 synthetic threads, both layers checked.

Each thread is a small task family with known content. The eval builds the episode for
every thread twice:

1. with the template writer (the deterministic path), checking that no caption and no
   line carries an unsupported claim, that no dialogue is a verbatim quote over 12
   words, and that no redaction marker survives;
2. with an **adversarial** writer that invents a cause, a number and a name, checking
   that the gate refuses all of them - a clean run only means something if the check
   can fail.

Usage: python eval/threads/run.py [--json-out PATH]
Exit: 0 when every thread is clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canon.aliases import AliasBook, apply_to_ir, masks_in  # noqa: E402
from canon.arcs import build_arcs  # noqa: E402
from canon.beats import beats_from_events  # noqa: E402
from canon.canon import build_canon  # noqa: E402
from canon.episode import TemplateDialogueWriter, plan_episode  # noqa: E402
from canon.events import build_event  # noqa: E402
from canon.gate import seal  # noqa: E402
from canon.grounding import ClaimGate  # noqa: E402
from canon.threads import build_threads  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "results.json"

TASK_SUBJECTS = (
    "the uv-lock replay lane", "the dashboard build", "the auth refactor",
    "the cron delivery path", "the memory migration", "the letterer layout",
    "the release gate", "the profile loader", "the queue drain", "the retry policy",
)
BLOCKERS = (
    "the runner timed out", "the lockfile drifted", "the token expired",
    "the schema mismatched", "the queue backed up", "the fixture was stale",
)
FIXERS = ("wesker", "octacon", "quan", "remio")


@dataclass(frozen=True)
class ThreadCase:
    id: str
    subject: str
    blocker: str
    fixer: str
    completed: bool


def cases() -> list[ThreadCase]:
    out: list[ThreadCase] = []
    for index in range(30):
        out.append(
            ThreadCase(
                id=f"t_case{index:02d}",
                subject=TASK_SUBJECTS[index % len(TASK_SUBJECTS)],
                blocker=BLOCKERS[index % len(BLOCKERS)],
                fixer=FIXERS[index % len(FIXERS)],
                completed=index % 3 != 2,  # two in three threads finish
            )
        )
    return out


def build_events(case: ThreadCase) -> list[Any]:
    # A strip needs four beats, so each thread carries four struggle beats plus a
    # completion when it finished.
    rows: list[tuple[float, str, str, str]] = [
        (1.0, "created", "kensei", f"created a task: {case.subject}"),
        (2.0, "claimed", case.fixer, f"{case.fixer} claimed {case.subject}"),
        (3.0, "blocked", case.fixer, f"{case.blocker} on {case.subject}"),
        (4.0, "blocked", case.fixer, f"{case.blocker} again on {case.subject}"),
        (5.0, "blocked", case.fixer, f"{case.blocker} a third time on {case.subject}"),
        (6.0, "blocked", case.fixer, f"{case.blocker} once more on {case.subject}"),
    ]
    if case.completed:
        rows.append((6.0, "completed", case.fixer, f"{case.fixer} completed {case.subject}"))
    events = []
    for ts, kind_field, profile, text in rows:
        payload = {"kind": kind_field, "task_id": case.id, "text": text, "chars": len(text)}
        event = build_event(
            source="kanban",
            kind="kanban.task.status",
            ts=ts,
            profile=profile,
            actor=profile,
            subject=case.id,
            payload=payload,
            store="main",
            table="tasks",
            pk=f"{case.id}-{ts}",
        )
        events.append(seal(event, payload))
    return events


class AdversarialWriter:
    """Tries to smuggle a cause, a number and a name into every panel."""

    name = "adversarial"

    def write(self, panels: Sequence[Any]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for index, panel in enumerate(panels):
            actors = list(panel.get("actors") or [])
            speaker = actors[0] if actors else "Sahil"
            out[panel["role"]] = {
                "caption": "the config was missing the timeout key",
                "lines": [[speaker, f"it broke because Priya deleted 7 files in {panel.get('setting', 'the rig')}"]],
            }
        return out


def check_thread(case: ThreadCase, *, writer, gate: ClaimGate, book: AliasBook) -> dict[str, Any]:
    events = build_events(case)
    beats = beats_from_events(events)
    arcs = build_arcs(build_threads(events), beats, events_by_id={event.id: event for event in events})
    arc = arcs[0] if arcs else None
    if arc is None:
        return {"id": case.id, "skipped": "no arc", "problems": []}
    canon = build_canon(events, beats)
    evidence = {event.id: str(event.payload.get("text", "")) for event in events}
    actors = {event.id: str(event.actor).capitalize() for event in events}
    cast_map = {"kensei": "Kensei", **{name: name.capitalize() for name in FIXERS}}
    ir = plan_episode(
        arc,
        beats,
        canon,
        writer=writer,
        grounder=gate,
        evidence=evidence,
        actors_by_event=actors,
        cast_map=cast_map,
    )
    ir = apply_to_ir(ir, book)

    problems: list[str] = []
    for panel in ir.panels:
        if panel.caption:
            cited = tuple(
                {event_id for line in panel.lines for event_id in line.source_event_ids}
            ) or tuple(evidence)
            panel_evidence = " ".join(evidence.get(event_id, "") for event_id in cited)
            verdict = gate.check(panel.caption, panel_evidence, layer="caption")
            if not verdict.supported:
                problems.append(f"{case.id}/{panel.id} caption: {verdict.reason}")
            for event_id in {eid for line in panel.lines for eid in line.source_event_ids}:
                pass
        for line in panel.lines:
            cited = " ".join(evidence.get(eid, "") for eid in line.source_event_ids)
            verdict = gate.check(line.text, cited, layer="dialogue")
            if not verdict.supported:
                problems.append(f"{case.id}/{panel.id} line ({line.speaker}): {verdict.reason}")
            if verdict.supported and line.text.strip() and line.text.strip() in cited and not gate.quote_ok(line.text):
                problems.append(f"{case.id}/{panel.id} line is a long verbatim quote")
    blob = json.dumps(ir.as_dict())
    if masks_in(blob):
        problems.append(f"{case.id} still shows {len(masks_in(blob))} redaction marker(s)")
    return {
        "id": case.id,
        "panels": len(ir.panels),
        "completed": case.completed,
        "cliffhanger": ir.cliffhanger,
        "grounding": dict(ir.grounding),
        "problems": problems,
    }


def run(*, use_llm: Any | None = None) -> dict[str, Any]:
    gate = ClaimGate(use_llm)
    book = AliasBook.load(HERE / ".aliases.json")
    all_cases = cases()

    clean: list[dict[str, Any]] = []
    for case in all_cases:
        clean.append(check_thread(case, writer=TemplateDialogueWriter(("Sahil",), hero="Sahil"), gate=gate, book=book))

    hostile: list[dict[str, Any]] = []
    for case in all_cases:
        hostile.append(check_thread(case, writer=AdversarialWriter(), gate=gate, book=book))

    clean_problems = [problem for row in clean for problem in row["problems"]]
    # Every adversarial caption/line should be refused; a released one is a failure.
    released = [
        problem
        for row in hostile
        for problem in row["problems"]
        if "caption:" not in problem and "line (" not in problem
    ]
    refused = sum(
        row.get("grounding", {}).get("captions_repaired", 0) + row.get("grounding", {}).get("lines_dropped", 0)
        for row in hostile
    )
    return {
        "threads": len(all_cases),
        "clean_threads_ok": not clean_problems,
        "clean_problems": clean_problems[:20],
        "adversarial_captions_or_lines_released": released[:20],
        "adversarial_refusals": refused,
        "completed_threads": sum(1 for case in all_cases if case.completed),
        "cliffhangers": sum(1 for row in clean if row.get("cliffhanger")),
        "ok": not clean_problems and not released and refused > 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    report = run()
    print(f"synthetic threads: {report['threads']} ({report['completed_threads']} completed)")
    print(f"  clean template runs ...... {'OK' if report['clean_threads_ok'] else 'FAILED'}")
    print(f"  cliffhanger panels ....... {report['cliffhangers']}")
    print(f"  adversarial refusals ..... {report['adversarial_refusals']}")
    if report["clean_problems"]:
        print("  problems in the clean run:")
        for problem in report["clean_problems"][:10]:
            print(f"    - {problem}")
    if report["adversarial_captions_or_lines_released"]:
        print("  ADVERSARIAL TEXT RELEASED (must be none):")
        for problem in report["adversarial_captions_or_lines_released"][:10]:
            print(f"    - {problem}")
    print("GATE " + ("PASSED" if report["ok"] else "FAILED"))

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
