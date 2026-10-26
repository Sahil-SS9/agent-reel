#!/usr/bin/env python3
"""Replay every citation in an episode trace from the trace alone (t_abdaa3a9).

Quan's re-sample at 0689404 could not replay 4-6 statement lines: the trace kept only
the cited events, cut to 1,200 characters, so the word overlap the citations were ranked
by was lost. A trace now archives the exact runtime evidence pool (whole, in ranking
order, with its sha256), each panel's own event ids, the pre-alias caption and line text,
and the fact source texts. This tool re-runs the planner's own citation functions on
that archive and compares the result with what the planner cited.

Usage: python -m eval.trace_replay <episode-N-trace.json> [--json-out PATH]
Exit: 0 when the pool digest matches and every caption and line replays exactly; 1 when
anything differs; 2 when the trace predates the archive (no evidence_pool).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from canon.episode import caption_citation, line_kind, pool_digest, support_events


def replay(trace: dict[str, Any]) -> dict[str, Any]:
    archive = trace.get("evidence_pool")
    if not isinstance(archive, dict):
        return {"ok": False, "error": "trace has no evidence_pool (written before t_abdaa3a9)"}
    events = archive.get("events") or {}
    order = list(archive.get("order") or [])
    pool = {event_id: str(events.get(event_id, "")) for event_id in order}
    digest = pool_digest(pool)
    sources = list(archive.get("fact_source_texts") or [])
    facts = [
        SimpleNamespace(
            event_id=fact.get("event_id", ""),
            object=fact.get("object", ""),
            result=fact.get("result", ""),
            source_text=sources[index] if index < len(sources) else "",
        )
        for index, fact in enumerate(trace.get("facts") or [])
    ]
    caption_pool = {event_id: pool.get(event_id, "") for event_id in archive.get("caption_pool_ids") or []}
    rows: list[dict[str, Any]] = []
    for panel in trace.get("panels") or []:
        own = list(panel.get("own_event_ids") or [])
        caption = str(panel.get("caption") or "")
        if caption:
            got = list(caption_citation(caption, own, caption_pool, facts))
            rows.append({
                "panel": panel["id"], "kind": "caption", "text": caption,
                "cited": panel.get("caption_source_event_ids"), "replayed": got,
                "match": got == list(panel.get("caption_source_event_ids") or []),
            })
        for line in panel.get("lines") or []:
            text = str(line.get("text") or "")
            kind = line_kind(text)
            if kind == "reaction":
                got = own
            else:
                got, _ = support_events(text, own, pool, order)
            rows.append({
                "panel": panel["id"], "kind": kind, "speaker": line.get("speaker"), "text": text,
                "cited": line.get("source_event_ids"), "replayed": list(got),
                "match": list(got) == list(line.get("source_event_ids") or []),
            })
    inexact = list(archive.get("regated_ids") or [])
    return {
        "ok": digest == archive.get("sha256") and all(row["match"] for row in rows) and not inexact,
        "pool_sha256_recorded": archive.get("sha256"),
        "pool_sha256_replayed": digest,
        "pool_events": len(pool),
        "regated_ids": inexact,
        "replayed": len(rows),
        "matched": sum(1 for row in rows if row["match"]),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay every citation in an episode trace.")
    parser.add_argument("trace", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    result = replay(json.loads(args.trace.read_text(encoding="utf-8")))
    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    if "error" in result:
        print(result["error"])
        return 2
    print(
        f"pool {result['pool_events']} events, sha256 "
        f"{'matches' if result['pool_sha256_recorded'] == result['pool_sha256_replayed'] else 'DIFFERS'}; "
        f"replayed {result['matched']}/{result['replayed']} citations exactly"
        + (f"; inexact (re-gated) ids: {result['regated_ids']}" if result["regated_ids"] else "")
    )
    for row in result["rows"]:
        if not row["match"]:
            print(f"  MISMATCH {row['panel']} {row['kind']}: {row['text'][:70]!r} cited={row['cited']} replayed={row['replayed']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
