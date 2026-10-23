#!/usr/bin/env python3
"""Grounding cases: known evidence, a grounded line, and an invented one.

Audit M1-F1: the live script invented "GGUF latency", "missing timeout key" and "fix it
or the rig burns down" from beats that cited only tool and skill names. This dataset
pairs each piece of evidence with one line that is supported by it and one that looks
plausible but is not. The gate must release the first and refuse the second.

Usage: python eval/grounding/run.py [--json-out PATH]
Exit: 0 when 0 unsupported lines are released, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canon.grounding import ClaimGate  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "results.json"

#: (evidence, grounded line, invented line). Every invented line adds a cause, a
#: component, a number or an outcome that the evidence does not contain.
CASES: list[tuple[str, str, str]] = [
    (
        "denji-reviewer blocked the task after 2 failures. outcome: gave_up",
        "denji-reviewer blocked it after 2 failures.",
        "the config was missing the timeout key.",
    ),
    (
        "the dispatcher claimed t_ab12 and ran it for 40 minutes",
        "the dispatcher ran it for 40 minutes.",
        "the GPU was throttling at 91 degrees.",
    ),
    (
        "wesker restarted the gateway and the queue drained",
        "wesker restarted the gateway.",
        "the queue drained because the database was corrupted.",
    ),
    (
        "octacon patched 7 files in the pipeline package",
        "octacon patched 7 files.",
        "the patch fixed the off-by-one in the scheduler.",
    ),
    (
        "cron job moss-pr-feedback-loop completed at 09:55",
        "moss-pr-feedback-loop completed at 09:55.",
        "the cron failed because the API key had expired.",
    ),
    (
        "skill hermes-cron-operations was used 12 times this week",
        "hermes-cron-operations was used 12 times.",
        "the skill was written to fix a broken scheduler.",
    ),
    (
        "remii read 3 papers and summarised 1",
        "remii summarised 1 paper.",
        "the paper proposed a new attention mechanism.",
    ),
    (
        "task t_cd34 created by kensei, assignee quan",
        "task t_cd34 was created by kensei.",
        "quan rejected it because the tests were flaky.",
    ),
    (
        "the build failed with a linker error on the rust crate",
        "the build failed with a linker error.",
        "the linker error came from a missing system library.",
    ),
    (
        "the model answered in 2.8 seconds with thinking disabled",
        "the model answered in 2.8 seconds.",
        "disabling thinking halved the latency.",
    ),
    (
        "gojo archived 4 email threads and drafted 2 replies",
        "gojo drafted 2 replies.",
        "the replies were approved by the client.",
    ),
    (
        "the redaction benchmark caught 232 of 232 items",
        "the benchmark caught 232 items.",
        "the benchmark was written by an independent reviewer.",
    ),
    (
        "kanban task t_1f2e moved from blocked to done after 3 comments",
        "t_1f2e moved from blocked to done.",
        "the comments showed the owner had approved the budget.",
    ),
    (
        "a session started at 11:17 and ended at 11:59",
        "the session ended at 11:59.",
        "the session crashed because memory ran out.",
    ),
    (
        "the letterer placed 6 balloons and passed the vision check",
        "the letterer placed 6 balloons.",
        "the vision check failed on the third balloon.",
    ),
    (
        "memory snapshot stored 13 facts as hashes",
        "the snapshot stored 13 facts.",
        "the snapshot was deleted by the auditor.",
    ),
    (
        "cron job blog-pregen ran 24 times and failed 0 times",
        "blog-pregen ran 24 times.",
        "the blog posts were published to LinkedIn automatically.",
    ),
    (
        "the arc used beats from one kanban thread, 6 beats",
        "the arc used 6 beats.",
        "the arc is now causally verified end to end.",
    ),
    (
        "mrhermagi delivered lesson 14 on attention",
        "mrhermagi delivered lesson 14.",
        "the lesson covered flash attention in depth.",
    ),
    (
        "the pipeline gated 81,152 events and quarantined 0",
        "the pipeline gated 81,152 events.",
        "the pipeline quarantined 3 events for secrets.",
    ),
    (
        "triage-router assigned 9 tasks to specialists",
        "triage-router assigned 9 tasks.",
        "the tasks were all completed within the hour.",
    ),
    (
        "the episode script came from writer: llm, 6 panels",
        "the script has 6 panels.",
        "the script was reviewed by the owner before render.",
    ),
    (
        "light wrote a runbook for the gateway restart",
        "light wrote a runbook.",
        "the runbook documented the systemd unit names.",
    ),
    (
        "quan signed off release 0.3.4 after the regression suite",
        "quan signed off the release.",
        "the release shipped to production the same day.",
    ),
    (
        "the terminal command exited 0 after 41 seconds",
        "the command exited 0.",
        "the command was slow because of a network timeout.",
    ),
    (
        "denji-monitor flagged a block loop on t_9a8b",
        "denji-monitor flagged a block loop.",
        "the block loop was caused by a missing dependency.",
    ),
    (
        "ceecee drafted 3 posts and held them for approval",
        "ceecee drafted 3 posts.",
        "the posts were scheduled for Monday morning.",
    ),
    (
        "the cache answered 15 calls and called the model 5 times",
        "the cache answered 15 calls.",
        "the cache reduced cost by 60 per cent.",
    ),
    (
        "the pipeline read 67 profile stores read-only",
        "the pipeline read 67 stores.",
        "one store was corrupted and had to be repaired.",
    ),
    (
        "the writer produced 8 lines and 0 were dropped",
        "the writer produced 8 lines.",
        "the writer used the GPT Image provider for the art.",
    ),
    (
        "the fixture home has 4 profiles and 5 skills each",
        "the fixture has 4 profiles.",
        "the fixture was generated from real history.",
    ),
    (
        "the audit ran 5 findings past the builder",
        "the audit ran 5 findings past the builder.",
        "all 5 findings were accepted without discussion.",
    ),
]


def run(gate: ClaimGate) -> dict[str, Any]:
    released_unsupported: list[dict[str, str]] = []
    rejected_supported: list[dict[str, str]] = []
    for index, (evidence, grounded, invented) in enumerate(CASES, start=1):
        good = gate.check(grounded, evidence, layer="caption")
        if not good.supported:
            rejected_supported.append(
                {"case": index, "line": grounded, "reason": good.reason}
            )
        bad = gate.check(invented, evidence, layer="caption")
        if bad.supported:
            released_unsupported.append({"case": index, "line": invented})
    total = len(CASES)
    return {
        "cases": total,
        "grounded_lines_passed": total - len(rejected_supported),
        "invented_lines_refused": total - len(released_unsupported),
        "released_unsupported": released_unsupported,
        "rejected_supported": rejected_supported,
        "model_calls": gate.model_calls,
        "failures": gate.failures,
        "ok": not released_unsupported,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    parser.add_argument("--llm", choices=("none", "local"), default="none")
    parser.add_argument("--llm-url", default=None)
    args = parser.parse_args(argv)

    cached = None
    if args.llm == "local":
        if not args.llm_url:
            parser.error("--llm local needs --llm-url")
        from adapters.hermes.llm import OpenAICompatLLMClient
        from canon.cache import ModelCache
        from canon.llm import CachedLLM

        client = OpenAICompatLLMClient(
            base_url=args.llm_url,
            model="auto",
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        cached = CachedLLM(client, ModelCache(HERE / ".cache"), stage="grounding-eval")

    report = run(ClaimGate(cached))
    print(f"grounding eval: {report['cases']} cases (model pass = {args.llm == 'local'})")
    print(f"  grounded lines accepted : {report['grounded_lines_passed']}/{report['cases']}")
    print(f"  invented lines refused   : {report['invented_lines_refused']}/{report['cases']}")
    if report["released_unsupported"]:
        print("  RELEASED UNSUPPORTED LINES (must be 0):")
        for row in report["released_unsupported"][:10]:
            print(f"    - case {row['case']}: {row['line']}")
    if report["rejected_supported"]:
        print("  grounded lines wrongly refused:")
        for row in report["rejected_supported"][:10]:
            print(f"    - case {row['case']}: {row['line']} ({row['reason']})")
    print("GATE " + ("PASSED: 0 unsupported claims released" if report["ok"] else "FAILED"))

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
