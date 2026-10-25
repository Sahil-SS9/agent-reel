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


#: Round 10: paraphrase cases. The original set only has near-quotes as its grounded
#: lines, so it rewarded the full-overlap rule that refused every reworded caption. Each
#: case pairs a true rewording with a subtle invention: wrong actor, flipped outcome,
#: added cause, added time, or a changed figure.
PARAPHRASE_CASES: list[tuple[str, str, str]] = [
    (
        "The verify step did not run. It needed approval and the approval prompt timed out after 5 minutes.",
        "The verification never ran: it needed approval and the prompt timed out after 5 minutes.",
        "The verification failed its tests, so the prompt timed out after 5 minutes.",
    ),
    (
        "Sahil picked option two and asked for a leaderboard shared across plugin users.",
        "Sahil chose option two and wants a shared leaderboard for everyone using the plugin.",
        "Sahil chose option three and wants a shared leaderboard for everyone using the plugin.",
    ),
    (
        "kensei stopped the run on purpose; exit 143 was a SIGTERM, not a crash.",
        "Kensei halted the run deliberately; exit 143 was a SIGTERM rather than a crash.",
        "The run crashed with exit 143 after a SIGTERM from the kernel.",
    ),
    (
        "Every re-run finished, the full test suite passes and no skill made the AI worse for any persona.",
        "All the re-runs completed, the whole suite passed, and no skill hurt any persona.",
        "Most re-runs completed, the whole suite passed, and one skill hurt a persona.",
    ),
    (
        "Severian scored 87.3 against LCM-X at 79.5 on LoCoMo; BEAM was a tie; LongMemEval still running.",
        "On LoCoMo, Severian beat LCM-X 87.3 to 79.5, with BEAM tied.",
        "On LoCoMo, Severian beat LCM-X 87.3 to 79.5, and won LongMemEval too.",
    ),
    (
        "quan opened a rig trial comparing Gemma-4-E4B-it with Qwen3-4B as the compressor.",
        "Quan began a rig trial pitting Gemma-4-E4B-it against Qwen3-4B as compressor.",
        "Quan's rig trial showed Qwen3-4B beating Gemma-4-E4B-it as compressor.",
    ),
    (
        "The reviewer marked question four, about sharing, as option 2.",
        "The reviewer answered the sharing question, number four, with option 2.",
        "The reviewer skipped the sharing question because it was unclear.",
    ),
    (
        "octacon fixed the flaky login test and pushed the branch for review.",
        "Octacon repaired the flaky login test and sent the branch for review.",
        "Octacon repaired the flaky login test and merged it straight to main.",
    ),
    (
        "The redaction gate caught 17 of 17 secrets and leaked nothing on the held-out set.",
        "On the held-out set the redaction gate stopped all 17 secrets with zero leaks.",
        "On the held-out set the redaction gate stopped 16 of 17 secrets.",
    ),
    (
        "wesker restarted the gateway at 09:40 and the backlog cleared.",
        "Wesker restarted the gateway at 09:40, and the backlog cleared.",
        "Wesker restarted the gateway at 09:40 after a memory leak, and the backlog cleared.",
    ),
    (
        "The image test is done: two comic pages in two styles. I have not looked at the pictures myself.",
        "The image test produced two comic pages in two styles, still unviewed by Kensei.",
        "The image test produced two comic pages that Kensei checked and approved.",
    ),
    (
        "sahil asked for a simpler explanation of the review.",
        "Sahil wanted the review explained more simply.",
        "Sahil rejected the review as wrong.",
    ),
]


#: V7 (25/10/26): plain-English retellings. The true line explains jargon by what it
#: meant; the invented line keeps the plain tone but adds or flips a fact. Run with the
#: gate in meaning mode; the old floor refuses most of the true lines by design.
MEANING_CASES: list[tuple[str, str, str]] = [
    (
        "The first verify attempt failed with exit 127 because the probe worktree lacked hermes.",
        "The first check failed because the test copy was missing a tool, not because of the code.",
        "The first check failed because the code had a bug in it.",
    ),
    (
        "kensei stopped the run on purpose; exit 143 was a SIGTERM, not a crash.",
        "Kensei pulled the plug himself. It wasn't a crash.",
        "The run crashed and Kensei had to restart it.",
    ),
    (
        "Commit bd1a001 was an intermediate pair, superseded by the final d610509 runs and verification.",
        "Those earlier runs were only a halfway step; the final runs replaced them.",
        "Those earlier runs were wrong and had to be thrown away.",
    ),
    (
        "512-character reads ran 12-27% faster but lost four questions on one set.",
        "Shorter reads made it 12-27% faster, but it got four questions wrong on one set.",
        "Shorter reads made it 12-27% faster with no loss in accuracy.",
    ),
    (
        "Handoff 3 measured: none of the eight arms passes the acceptance rule as written.",
        "Eight attempts, and not one cleared the bar.",
        "Eight attempts, and one finally cleared the bar.",
    ),
    (
        "Round-two corrections are applied and await re-check; not accepted yet.",
        "The fixes are in, but nobody has signed them off yet.",
        "The fixes are in and the reviewer has signed them off.",
    ),
    (
        "The gateway OOM-killed the worker at 02:10; Wesker raised the memory cap to 4 GB.",
        "At 02:10 the worker ran out of memory, so Wesker gave it more room: 4 GB.",
        "At 02:10 the worker ran out of memory, so Wesker gave it more room: 8 GB.",
    ),
    (
        "CI is red on main: the Windows runner times out installing deps.",
        "The build is failing because the Windows machine runs out of time setting up.",
        "The build is failing because a test on Linux broke.",
    ),
]


#: The cast the pipeline passes to its gate as allowed names (production does the same
#: with the run's cast map): a character naming another character is judged by meaning.
EVAL_CAST = ("Sahil", "Kensei", "Quan", "Octacon", "Wesker", "Severian")


def run(gate: ClaimGate) -> dict[str, Any]:
    released_unsupported: list[dict[str, str]] = []
    rejected_supported: list[dict[str, str]] = []
    cases = CASES + PARAPHRASE_CASES + (MEANING_CASES if getattr(gate, "meaning", False) else [])
    for index, (evidence, grounded, invented) in enumerate(cases, start=1):
        good = gate.check(grounded, evidence, layer="caption")
        if not good.supported:
            rejected_supported.append(
                {"case": index, "line": grounded, "reason": good.reason}
            )
        bad = gate.check(invented, evidence, layer="caption")
        if bad.supported:
            released_unsupported.append({"case": index, "line": invented})
    total = len(cases)
    paraphrase_ids = set(range(len(CASES) + 1, len(CASES) + len(PARAPHRASE_CASES) + 1))
    meaning_ids = set(range(len(CASES) + len(PARAPHRASE_CASES) + 1, total + 1))
    return {
        "meaning_mode": bool(getattr(gate, "meaning", False)),
        "meaning_cases": len(meaning_ids),
        "meaning_accepted": len(meaning_ids)
        - sum(1 for row in rejected_supported if row["case"] in meaning_ids),
        "paraphrase_cases": len(PARAPHRASE_CASES),
        "paraphrases_accepted": len(PARAPHRASE_CASES)
        - sum(1 for row in rejected_supported if row["case"] in paraphrase_ids),
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

    # QAR-M2-11: production plans in meaning mode, so the eval gates both modes.
    strict_report = run(ClaimGate(cached, allow=EVAL_CAST))
    meaning_report = run(ClaimGate(cached, allow=EVAL_CAST, meaning=True)) if cached is not None else None
    report = strict_report
    if meaning_report is not None:
        print(f"meaning mode: {meaning_report['meaning_cases']} plain-English cases run, "
              f"{meaning_report['meaning_accepted']} accepted, "
              f"{len(meaning_report['released_unsupported'])} inventions released")
        if meaning_report["released_unsupported"] or meaning_report["meaning_cases"] != len(MEANING_CASES):
            report = dict(strict_report, ok=False, released_unsupported=strict_report["released_unsupported"] + meaning_report["released_unsupported"])
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
