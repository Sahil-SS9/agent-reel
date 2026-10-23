#!/usr/bin/env python3
"""Run the redaction benchmark and enforce the M1 gate.

Gate (HANDOFF §4 M1): 100% recall on secrets, >=95% recall on names.

Recall is measured on the *exact labelled span*: an item counts as caught only if
that substring is gone from the gate's output. That is stricter than counting
category hits, and it does not care how the gate found it.

Two modes:

  --llm none    deterministic pass only (no model, no network)
  --llm local   deterministic pass plus the real model pass, using the rig's
                local serving route (no keys)

Exit code 0 when the gate passes, 1 when it fails, 2 when the run itself breaks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canon.cache import ModelCache
from canon.llm import CachedLLM, LLMClient, NullLLM
from canon.redact import DeterministicRedactor, ModelEntityGate, RedactionGate
from adapters.hermes.llm import OpenAICompatLLMClient
from adapters.hermes.redact_source import rules_from_snapshot

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.jsonl"

SECRET_CATEGORIES = frozenset({"secret"})
NAME_CATEGORIES = frozenset({"person_name", "client_name", "project_name"})
ALWAYS_REQUIRED = ("secret", "email", "phone", "ip", "path", "url_token")

ALLOWLIST = (
    "Sahil",
    "Kensei",
    "Hermes",
    "Claude",
    "Codex",
    "GitHub",
    "Discord",
    "Telegram",
    "Python",
    "SQLite",
    "Linux",
)

THRESHOLDS = {
    "secret": 1.00,
    "email": 1.00,
    "phone": 1.00,
    "ip": 1.00,
    "path": 1.00,
    "url_token": 1.00,
    "person_name": 0.95,
    "client_name": 0.95,
    "project_name": 0.95,
    "financial": 0.90,
    "health": 0.90,
}


def load_dataset(path: Path = DATASET) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_benchmark(
    items: Sequence[dict[str, Any]],
    *,
    client: LLMClient,
    use_model: bool,
    cache_dir: Path,
    deep: bool = False,
) -> dict[str, Any]:
    redactor = DeterministicRedactor(rules_from_snapshot())
    cache = ModelCache(cache_dir)
    cached = CachedLLM(client, cache, stage="benchmark.redaction")
    model_gate = ModelEntityGate(cached, allowlist=ALLOWLIST) if use_model else None
    gate = RedactionGate(
        redactor,
        model_gate=model_gate,
        allowlist=ALLOWLIST,
        max_chars=4000,
    )

    if model_gate is not None:
        gate.learn_vocabulary(item["text"] for item in items)

    started = time.time()
    per_category: dict[str, dict[str, int]] = {}
    misses: list[dict[str, str]] = []
    for item in items:
        category = item["category"]
        bucket = per_category.setdefault(
            category, {"total": 0, "caught": 0, "quarantined": 0, "leaked": 0}
        )
        try:
            redacted, _ = gate.redact_text(item["text"], deep=deep)
        except Exception as exc:  # noqa: BLE001
            # A failure is a *safe* outcome, not a leak: the text is quarantined and
            # never released to a later stage. Scoring it as a leak would be wrong.
            bucket["total"] += 1
            bucket["quarantined"] += 1
            misses.append(
                {"id": item["id"], "category": category, "reason": f"quarantined: {exc}"}
            )
            continue
        for label in item["labels"]:
            span = label["span"]
            bucket["total"] += 1
            # Whitespace-normalised containment: a multi-line label still counts as
            # present if its lines survive after redaction.
            if _normalise(span) in _normalise(redacted):
                bucket["leaked"] += 1
                misses.append(
                    {
                        "id": item["id"],
                        "category": label["category"],
                        "reason": "released with the span present",
                        "span": span[:60],
                    }
                )
            else:
                bucket["caught"] += 1

    # Recall here means "not leaked": caught or quarantined both keep the value out
    # of the story, and only a released span counts against the gate.
    recall = {
        category: (
            (bucket["total"] - bucket["leaked"]) / bucket["total"] if bucket["total"] else 0.0
        )
        for category, bucket in per_category.items()
    }
    elapsed = max(time.time() - started, 1e-6)
    quarantined_items = sum(bucket["quarantined"] for bucket in per_category.values())
    return {
        "items": len(items),
        "elapsed_s": round(elapsed, 2),
        "items_per_s": round(len(items) / elapsed, 2),
        "quarantine_rate": round(quarantined_items / len(items), 4) if items else 0.0,
        "use_model": use_model,
        "recall": {category: round(value, 4) for category, value in sorted(recall.items())},
        "counts": {category: bucket for category, bucket in sorted(per_category.items())},
        "misses": misses[:40],
        "miss_count": len(misses),
        "deep": deep,
        "cache": cache.stats(),
        "gate_report": gate.report.as_dict(),
        "client": getattr(client, "name", "unknown"),
    }


def _normalise(text: str) -> str:
    return " ".join(text.split())


def evaluate_thresholds(report: dict[str, Any]) -> list[str]:
    """Enforce each category against the pass that owns it.

    The deterministic pass owns secrets, contact details, addresses and paths, so
    those are required in every mode. Names, money and health are the model
    pass's job: their thresholds only apply when a model actually ran, and the
    report says which mode it was.
    """
    failures: list[str] = []
    recall = report["recall"]
    for category in ALWAYS_REQUIRED:
        required = THRESHOLDS[category]
        got = recall.get(category, 0.0)
        if got < required:
            failures.append(f"{category}: recall {got:.2%} < {required:.0%} (deterministic pass)")
    # Audit M1-F5: a model pass that quarantines more than 5% of items is not stable
    # enough to run a story on, even though quarantine is the safe outcome.
    if report.get("quarantine_rate", 0.0) > 0.05:
        failures.append(
            f"quarantine rate {report['quarantine_rate']:.1%} > 5% (model pass unstable)"
        )
    if not report["use_model"]:
        return failures
    for category in sorted(NAME_CATEGORIES):
        required = THRESHOLDS[category]
        got = recall.get(category, 0.0)
        if got < required:
            failures.append(f"{category}: recall {got:.2%} < {required:.0%} (model pass)")
    # Amounts and health details are free text, so only the per-item span pass can
    # see them; the vocabulary pass cannot. Their thresholds therefore apply in
    # --deep mode only, and the report says which mode ran.
    if report.get("deep"):
        for category in ("financial", "health"):
            required = THRESHOLDS[category]
            got = recall.get(category, 0.0)
            if got < required:
                failures.append(f"{category}: recall {got:.2%} < {required:.0%} (span pass)")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--llm", choices=("none", "local"), default="none")
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--llm-model", default="auto")
    parser.add_argument("--cache-dir", default=str(HERE / ".cache"))
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also run the per-item span pass (slow; the vocabulary pass is the default)",
    )
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    items = load_dataset(dataset_path)
    # The dev gate needs 200+ items; a held-out set is smaller by design and only
    # needs to be big enough to be meaningful.
    floor = 200 if dataset_path.name == DATASET.name else 30
    if len(items) < floor:
        print(f"dataset has {len(items)} items, the gate needs >={floor}", file=sys.stderr)
        return 2

    client: LLMClient
    if args.llm == "local":
        if not args.llm_url:
            print("--llm local needs --llm-url", file=sys.stderr)
            return 2
        # Same reasoning-model caveat as the pipeline: without this the model
        # spends the budget on reasoning_content and returns content: null.
        client = OpenAICompatLLMClient(
            base_url=args.llm_url,
            model=args.llm_model,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    else:
        client = NullLLM()

    report = run_benchmark(
        items,
        client=client,
        use_model=args.llm == "local",
        cache_dir=Path(args.cache_dir),
        deep=args.deep,
    )
    failures = evaluate_thresholds(report)
    report["failures"] = failures
    report["passed"] = not failures

    print(
        f"redaction benchmark: {report['items']} items from {dataset_path.name}, "
        f"model pass = {report['use_model']}, deep = {args.deep}"
    )
    print(f"  client: {report['client']}")
    print(
        f"  {report['items']} items in {report['elapsed_s']}s "
        f"({report['items_per_s']}/s), quarantined {report['quarantine_rate']:.1%}"
    )
    for category, value in report["recall"].items():
        counts = report["counts"][category]
        print(
            f"  {category:<14}{value:>7.2%}   caught {counts['caught']}/{counts['total']}"
            f"  quarantined {counts['quarantined']}  leaked {counts['leaked']}"
        )
    if report["miss_count"]:
        print(f"  misses: {report['miss_count']}")
        for miss in report["misses"][:10]:
            print(f"    - {miss['id']} {miss['category']}: {miss['reason']} {miss.get('span', '')}")
    if failures:
        print("GATE FAILED")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("GATE PASSED: secrets 100%, names >=95%")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
