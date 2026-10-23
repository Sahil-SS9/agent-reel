"""The redaction benchmark: dataset shape and the gate it enforces."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval" / "redaction"))

from eval.redaction.run import (  # noqa: E402  (path set above)
    ALWAYS_REQUIRED,
    evaluate_thresholds,
    load_dataset,
    run_benchmark,
)
from canon.llm import FakeLLM, NullLLM  # noqa: E402


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def test_dataset_is_big_enough_and_labelled(dataset):
    assert len(dataset) >= 200, "the gate requires at least 200 labelled items"
    categories = {item["category"] for item in dataset}
    assert {"secret", "email", "phone", "ip", "path", "url_token"} <= categories
    assert {"person_name", "client_name", "project_name"} <= categories
    for item in dataset:
        assert item["labels"], f"{item['id']} has no labels"
        for label in item["labels"]:
            assert label["span"] in item["text"], f"{item['id']} label is not in its text"


def test_dataset_contains_no_real_history(dataset):
    """Everything here is invented: no profile names, no repo paths, no live hosts."""
    blob = " ".join(item["text"] for item in dataset).lower()
    for fingerprint in ("kensei", "hermes-agent", "octacon", "wesker", "severian", "/home/kensei", "sahil"):
        assert fingerprint not in blob, f"dataset leaked a real fingerprint: {fingerprint}"


def test_deterministic_pass_meets_its_own_thresholds(dataset, tmp_path):
    report = run_benchmark(
        dataset, client=NullLLM(), use_model=False, cache_dir=tmp_path / "cache"
    )
    for category in ALWAYS_REQUIRED:
        assert report["counts"][category]["leaked"] == 0, f"{category} leaked"
        assert report["recall"][category] == pytest.approx(1.0)
    assert evaluate_thresholds(report) == []


def _name_classifier(payload):
    """A stand-in model that classifies names correctly, for plumbing tests."""
    known_names = {
        "Mike Harrington", "Priya Raman", "Dmitri Volkov", "Aoife Byrne", "Tomasz Nowak",
        "Chen Wei", "Fatima Al-Sayed", "Oluwaseun Adeyemi", "Rafael Mendoza", "Ingrid Larsson",
        "Hiroshi Tanaka", "Nnenna Okafor", "Sofia Rossi", "Jonas Weber", "Amara Diallo",
        "Elena Petrova", "Kwame Mensah", "Lucia Fernandez", "Arjun Mehta", "Zara Hussain",
        "Northwind Traders", "Bluepeak Analytics", "Halden & Rook", "Kestrel Labs",
        "Verdant Systems", "Pinewood Motors", "Ashgrove Legal",
        "Project Nightjar", "Operation Tinderbox", "The Hollow Crown", "Initiative Redshift",
        "Atlas Rebuild",
    }
    clients = {
        "Northwind Traders", "Bluepeak Analytics", "Halden & Rook", "Kestrel Labs",
        "Verdant Systems", "Pinewood Motors", "Ashgrove Legal",
    }
    projects = {
        "Project Nightjar", "Operation Tinderbox", "The Hollow Crown",
        "Initiative Redshift", "Atlas Rebuild",
    }

    def classify(candidate: str) -> str:
        # The candidate extractor splits on hyphens and may return a prefix, so
        # match the same way a reasonable model would.
        for known in known_names:
            if candidate == known or known.startswith(candidate) or candidate.startswith(known):
                if known in clients:
                    return "client_name"
                if known in projects:
                    return "project_name"
                return "person_name"
        return "safe"

    results = [
        {"name": name, "category": classify(name)} for name in payload["candidates"]
    ]
    return {"results": results}


def test_model_pass_catches_names_when_the_classifier_works(dataset, tmp_path):
    fake = FakeLLM({}, default=_name_classifier)
    report = run_benchmark(
        dataset, client=fake, use_model=True, cache_dir=tmp_path / "cache"
    )
    for category in ("person_name", "client_name", "project_name"):
        assert report["counts"][category]["leaked"] == 0, f"{category} leaked"
        assert report["recall"][category] >= 0.95
    assert evaluate_thresholds(report) == []


def test_model_pass_is_required_for_names(dataset, tmp_path):
    """Without a model, names are not caught - which is why the gate says so."""
    report = run_benchmark(
        dataset, client=NullLLM(), use_model=False, cache_dir=tmp_path / "cache"
    )
    assert report["counts"]["person_name"]["leaked"] > 0
    # ...and the deterministic gate still passes on its own categories.
    assert evaluate_thresholds(report) == []


def test_a_failed_item_counts_as_quarantined_not_leaked(dataset, tmp_path):
    class Exploding:
        name = "exploding"

        def complete_json(self, **_kwargs):
            from canon.llm import LLMError

            raise LLMError("model down")

    from canon.llm import CachedLLM
    from canon.cache import ModelCache

    cached = CachedLLM(Exploding(), ModelCache(tmp_path / "cache"), stage="t")
    report = run_benchmark(
        dataset, client=cached, use_model=True, cache_dir=tmp_path / "cache", deep=True
    )
    assert report["counts"]["secret"]["quarantined"] > 0
    assert report["counts"]["secret"]["leaked"] == 0
