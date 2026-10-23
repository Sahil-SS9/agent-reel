#!/usr/bin/env python3
"""Snapshot Hermes' redaction patterns so the core can reuse them offline.

HANDOFF §4 M1: "reuse Hermes' agent/redact.py patterns through the adapter". The
core must not import Hermes (decision D2), so the adapter carries a JSON snapshot
of the parts that are plain literals, with provenance (ref + commit), and
regenerates it with this script.

Extraction is done with ``ast``, not regex scraping: the values are string
literals in the module, so this cannot silently pick up a comment or half a line.

Usage:
    python scripts/extract_hermes_redact.py            # writes the snapshot
    python scripts/extract_hermes_redact.py --check    # exit 1 if it would change
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "adapters" / "hermes" / "hermes_redact_patterns.json"
VANILLA = Path.home() / "repos" / "hermes-agent-vanilla"
#: Pinned to the commit the pack verified its surfaces against (docs/hermes-surfaces.md),
#: so the snapshot is reproducible. Bump it deliberately, with a report note.
REF = "a4072ce7e67313eda344de4e4d691b6a5ba50164"
SOURCE_PATH = "agent/redact.py"

#: Names whose values are plain literals we can lift verbatim.
STRING_LISTS = ("_PREFIX_PATTERNS", "SECRET_HEADER_NAME_LIST")
STRING_CONSTANTS = (
    "_SECRET_ENV_NAMES",
    "_SECRET_CFG_NAMES",
    "_YAML_CFG_NAMES",
    "_JSON_KEY_NAMES",
)


def _read_source() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "-C", str(VANILLA), "rev-parse", f"{REF}^{{commit}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    text = subprocess.run(
        ["git", "-C", str(VANILLA), "show", f"{REF}:{SOURCE_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return commit, text


def extract(text: str) -> dict[str, object]:
    tree = ast.parse(text)
    found: dict[str, object] = {}
    for node in ast.walk(tree):
        targets: list[str] = []
        value = None
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if not targets or value is None:
            continue
        for name in targets:
            if name in STRING_LISTS and isinstance(value, (ast.List, ast.Tuple)):
                items = [
                    elt.value
                    for elt in value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
                found[name] = items
            elif name in STRING_CONSTANTS and isinstance(value, ast.Constant):
                if isinstance(value.value, str):
                    found[name] = value.value
    missing = [n for n in STRING_LISTS + STRING_CONSTANTS if n not in found]
    if missing:
        raise SystemExit(f"could not extract from {SOURCE_PATH}: {missing}")
    return found


def build() -> dict[str, Any]:
    commit, text = _read_source()
    extracted = extract(text)
    payload = {
        "source": {
            "repo": "NousResearch/hermes-agent",
            "path": SOURCE_PATH,
            "ref": REF,
            "commit": commit,
            "extracted_by": "scripts/extract_hermes_redact.py",
            "note": (
                "Vendor token prefixes and secret-name vocabularies lifted verbatim "
                "from Hermes' redaction module. The composing regexes live in "
                "adapters/hermes/redact_source.py."
            ),
        },
        "prefix_patterns": extracted["_PREFIX_PATTERNS"],
        "secret_header_names": extracted["SECRET_HEADER_NAME_LIST"],
        "secret_env_names": extracted["_SECRET_ENV_NAMES"],
        "secret_cfg_names": extracted["_SECRET_CFG_NAMES"],
        "yaml_cfg_names": extracted["_YAML_CFG_NAMES"],
        "json_key_names": extracted["_JSON_KEY_NAMES"],
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the snapshot is stale")
    args = parser.parse_args(argv)

    payload = build()
    rendered = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != rendered:
            print(f"{OUT} is stale; re-run without --check", file=sys.stderr)
            return 1
        print(f"{OUT} is up to date ({len(payload['prefix_patterns'])} prefixes)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {OUT} ({len(payload['prefix_patterns'])} prefixes, "
        f"commit {payload['source']['commit'][:12]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
