"""F3: the read-only claim must be exact, everywhere it is made."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EXACT_PHRASE = "no files created, renamed, truncated or deleted"
WAL_INDEX_PHRASE = "wal-index pages"
# The gate text itself ("show no write opens under ~/.hermes, OR ...") is quoted
# in the report, so only the *claims* are checked here.
OVERCLAIMS = (
    "Nothing under `~/.hermes` is written",
    "nothing under `~/.hermes` is written",
)


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_schema_doc_states_the_exact_claim():
    text = _read("canon/HERMES_SCHEMA.md")
    assert EXACT_PHRASE in text.lower()
    assert WAL_INDEX_PHRASE in text
    assert "read locking" in text


def test_m0_report_states_the_exact_claim():
    text = _read("docs/reports/M0-REPORT.md")
    assert EXACT_PHRASE in text.lower()
    assert WAL_INDEX_PHRASE in text


def test_readme_states_the_exact_claim():
    text = _read("README.md")
    assert "no file is created, renamed" in text


def test_proof_script_states_the_exact_claim():
    text = _read("scripts/readonly_proof.sh")
    assert "no file is created, renamed, truncated or deleted" in text
    assert WAL_INDEX_PHRASE in text


# ---------------------------------------------------------------- F4: $TMPDIR

DOC_FILES = (
    "README.md",
    "canon/HERMES_SCHEMA.md",
    "docs/reports/M0-REPORT.md",
    "scripts/readonly_proof.sh",
)


#: The system temp dir as a path, but not `$SCRATCH/tmp` or `tmp_path`.
_SYSTEM_TMP = re.compile(r"(?<![\w$])/tmp(?:/|\"|\s|$)")


def test_docs_and_examples_use_tmpdir_not_slash_tmp():
    """The rig convention is $TMPDIR; the system temp dir is never for scratch work."""
    offenders = []
    for rel in DOC_FILES:
        for number, line in enumerate(_read(rel).splitlines(), start=1):
            if _SYSTEM_TMP.search(line):
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert offenders == [], "use $TMPDIR instead of the system temp dir:\n" + "\n".join(offenders)


def test_examples_export_tmpdir_with_the_rig_default():
    text = _read("docs/reports/M0-REPORT.md")
    assert 'export TMPDIR="${TMPDIR:-$HOME/.hermes/cache/scratch}"' in text
    assert "$TMPDIR/reel-synthetic" in text


def test_no_overclaim_remains():
    for rel in ("canon/HERMES_SCHEMA.md", "docs/reports/M0-REPORT.md", "README.md"):
        text = _read(rel)
        for overclaim in OVERCLAIMS:
            assert overclaim not in text, f"{rel} still overclaims: {overclaim!r}"
