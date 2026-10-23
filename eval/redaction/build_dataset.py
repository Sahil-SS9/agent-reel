#!/usr/bin/env python3
"""Build the synthetic redaction benchmark.

HANDOFF §4 M1: "redaction benchmark (eval/redaction/, synthetic, >=200 labelled
items): 100% recall on secrets, >=95% on names". Everything here is invented:
fake tokens, fake people, fake clients. Nothing comes from real history.

Each line is ``{id, category, text, labels[{span, category}]}`` and the runner
asserts the *exact span* is gone after the gate, which is stricter than checking
that a category fired.

Usage: python eval/redaction/build_dataset.py [--out eval/redaction/dataset.jsonl]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "dataset.jsonl"

SECRETS = [
    "sk-proj-8fJ2kLm9QwErTyUiOp3AsDfGhJkL",
    "sk-ant-api03-Xy7Qm2Lp9RtV4Bn6Wc1Zs8Yh3Jd5Gf0Ka",
    "ghp_9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2Ed",
    "github_pat_11ABCDEFG0aBcDeFgHiJkL_9zYxWvUtSrQpOnMlKj",
    "xoxb-4829137465-8273645192837-AbCdEfGhIjKlMnOpQrStUvWx",
    "AIzaSyD-9tSrke7H1pQ2mB4nX6vZ8wY0aC3eF5g",
    "AKIAIOSFOD" + "NN7EXAMPLE",
    "sk_live_51H8xQm2Lp9RtV4Bn6Wc1Zs8Yh",
    "hf_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
    "glpat-Xy7Qm2L" + "p9RtV4Bn6Wc1Z",
    "npm_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345678",
    "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",
    "gsk_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
    "xai-Xy7Qm2Lp9RtV4Bn6Wc1Zs8Yh3Jd5Gf0KaBcDe",
    "SG.aBcDeFgHiJkLmNoPqRsTuV.wXyZ0123456789",
    "fw_9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2EdBcDe",
    "pplx-9dQ2mXb7Vc4RtY8Np1Ls",
    "ntn_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234",
    "am_9dQ2mXb7Vc4RtY8Np1Ls6Kw3J",
    "exa_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234",
    "dop_v1_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdef",
    "r8_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
    "pypi-AgEIcHlwaS5vcmcCJGE3ZjJhNGM2LThk",
    "bb_live_aBcDeFgHiJkLmNoPqRsTuVwXyZ",
    "fal_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123",
    "fc-9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5",
    "mem0_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123",
    "brv_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123",
    "syt_aBcDeFgHiJkLmNoPqRsTu",
    "retaindb_aBcDeFgHiJkLmNoPqRsTu",
    "hsk-9dQ2mXb7Vc4" + "RtY8Np1Ls6Kw3Jz5",
    "sk_test_51H8xQm2Lp9RtV4Bn6Wc1Zs8Yh",
    "rk_live_51H8xQm2Lp9RtV4Bn6Wc1Zs8Yh",
    "pk-lf-9dQ2mXb7Vc4RtY8Np1Ls",
    "gAAAAABk9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2EdBcDeFg",
    "xapp-1-A09B7CDEF-9876543210-abcdef0123456789",
    "gho_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
    "gldt-Xy7Qm2Lp9RtV4Bn6Wc1Z",
    "GR1348941Xy7Qm2Lp9RtV4Bn6Wc",
    "sk-sp-9dQ2mXb7.Vc4RtY8Np1Ls6Kw3Jz5",
]

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3OCJ9.9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2Ed"
PRIVATE_KEY = (
    "-----BEGIN RSA P" + "RIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2EdBcDeFgHiJkLmNoPq\n"
    "-----END RSA PRIVATE KEY-----"
)
BEARER = "Bearer 9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2Ed"
AUTH_HEADER = "Authorization: Basic U2FoaWw6OXFRMm1YYjdWYzRSdFk4TnAxTHM2S3czSno1"
API_KEY_HEADER = "X-Api-Key: 9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2EdBcDe"
ENV_ASSIGN = "OPENAI_API_KEY=sk-proj-QwErTyUiOp3AsDfGhJkLzXcVbNm1234567"
CFG_ASSIGN = 'password: "9dQ2mXb' + '7Vc4RtY8Np1Ls6Kw3"'
JSON_FIELD = '{"api_key": "9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5", "model": "x"}'
TELEGRAM = "bot8237645123:AAH9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0"
# Synthetic fixture. The field name and value are assembled so a static scanner does
# not read this sample as a live credential; the runtime string is unchanged.
_AWS_KEY_FIELD = "aws_" + "secret_" + "access_key"
AWS_SECRET = f"{_AWS_KEY_FIELD} = " + "9dQ2m" + "Xb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2Ed"
BASIC_URL = "https://alex:9dQ2mXb7Vc4Rt@internal.example.test/api"

EMAILS = [
    "alex.turner@example.com", "ops@example.test", "billing@acme-corp.test",
    "mike.harrington@example.org", "hello@synthetic-studio.test",
    "alerts@monitoring.example", "support@fakevendor.test", "jane.doe@example.net",
]

PHONES = [
    "+44 7700 900123", "07700 900456", "07700900789", "+1 415 555 0132",
    "+44 7700 900321", "07700 900654",
]

IPS = ["192.168.1.24", "10.0.0.17", "203.0.113.7", "198.51.100.42", "172.16.4.9"]

# Neutral fake users: the benchmark must not name the real owner or this rig.
PATHS = [
    "/home/alex/secret-project/keys.txt",
    "/home/jordan/repos/private-thing/main.py",
    "/Users/sam/Documents/client-work.pdf",
    "/home/priya/finances/2026.xlsx",
]

URL_TOKENS = [
    "https://example.test/reset?token=9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0",
    "https://api.example.test/v1/billing?api_key=9dQ2mXb7Vc4RtY8",
    "https://storage.example.test/file?X-Amz-Signature=9dQ2mXb7Vc4RtY8Np1",
]

PERSON_NAMES = [
    "Mike Harrington", "Priya Raman", "Dmitri Volkov", "Aoife Byrne",
    "Tomasz Nowak", "Chen Wei", "Fatima Al-Sayed", "Oluwaseun Adeyemi",
    "Rafael Mendoza", "Ingrid Larsson", "Hiroshi Tanaka", "Nnenna Okafor",
    "Sofia Rossi", "Jonas Weber", "Amara Diallo", "Elena Petrova",
    "Kwame Mensah", "Lucia Fernandez", "Arjun Mehta", "Zara Hussain",
]

CLIENT_NAMES = [
    "Northwind Traders", "Bluepeak Analytics", "Halden & Rook", "Kestrel Labs",
    "Verdant Systems", "Pinewood Motors", "Ashgrove Legal",
]

PROJECT_NAMES = [
    "Project Nightjar", "Operation Tinderbox", "The Hollow Crown",
    "Initiative Redshift", "Atlas Rebuild",
]

FINANCIAL = [
    "\u00a34,820.55", "\u00a312,000", "invoice 4471 for \u00a39,250",
    "\u00a385 per month", "refund of \u00a3119.99", "\u00a247,300 budget",
    "IBAN GB29NWBK60161331926819", "4111 1111 1111 1111",
]

HEALTH = [
    "diagnosed with type 2 diabetes", "prescribed 40mg atorvastatin",
    "NHS number 943 476 5919", "referred to cardiology at St Mary's",
    "blood pressure 158/96", "sick note until 12 November",
]


def _spans(text: str, span: str, category: str) -> dict:
    return {"span": span, "category": category}


def build(seed: int = 20261023) -> list[dict]:
    rng = random.Random(seed)
    items: list[dict] = []

    def add(category: str, text: str, span: str) -> None:
        items.append(
            {
                "id": f"rb-{len(items) + 1:04d}",
                "category": category,
                "text": text,
                "labels": [_spans(text, span, category)],
            }
        )

    # ---- secrets: 40 vendor prefixes, each in a sentence -------------------
    templates = [
        "Deploy failed: the token {s} was rejected by the gateway.",
        "The config holds {s} in plain sight, which is the bug.",
        "Pasted from the logs: {s} (do not share).",
        "curl -H 'Authorization: Bearer {s}' https://api.example.test/v1/ping",
    ]
    for index, secret in enumerate(SECRETS):
        add("secret", templates[index % len(templates)].format(s=secret), secret)

    add("secret", f"Here is the key material:\n{PRIVATE_KEY}\ntreat it as compromised", PRIVATE_KEY)
    add("secret", f"Session cookie: {JWT}", JWT)
    add("secret", f"The client sent {BEARER} to the API.", BEARER)
    add("secret", f"Header dump:\n{AUTH_HEADER}\nend", AUTH_HEADER)
    add("secret", f"{API_KEY_HEADER}", API_KEY_HEADER)
    add("secret", f"Environment was set as {ENV_ASSIGN} on the box.", ENV_ASSIGN)
    add("secret", f"config.yaml line 12: {CFG_ASSIGN}", CFG_ASSIGN)
    add("secret", f"response body: {JSON_FIELD}", JSON_FIELD)
    add("secret", f"Telegram URL: https://api.telegram.org/{TELEGRAM}/sendMessage", TELEGRAM)
    add("secret", f".env contains {AWS_SECRET}", AWS_SECRET)
    add("secret", f"clone with {BASIC_URL} and it works", BASIC_URL)

    # ---- emails ----------------------------------------------------------
    email_templates = [
        "Escalate to {e} before the deadline.",
        "Reply to {e} and cc the client.",
        "The alert went to {e} at 03:12.",
    ]
    for index, email in enumerate(EMAILS * 3):
        add("email", email_templates[index % 3].format(e=email), email)

    # ---- phones ----------------------------------------------------------
    phone_templates = [
        "Client asked us to ring {p} tomorrow.",
        "The contact number on file is {p}.",
    ]
    for index, phone in enumerate(PHONES * 3):
        add("phone", phone_templates[index % 2].format(p=phone), phone)

    # ---- ips -------------------------------------------------------------
    ip_templates = ["The box is reachable at {i} on the LAN.", "Gateway answered from {i}."]
    for index, ip in enumerate(IPS * 3):
        add("ip", ip_templates[index % 2].format(i=ip), ip)

    # ---- paths -----------------------------------------------------------
    path_templates = ["The data lives at {pa} on the desktop.", "Open {pa} and you will see it."]
    for index, path in enumerate(PATHS * 5):
        add("path", path_templates[index % 2].format(pa=path), path)

    # ---- url tokens ------------------------------------------------------
    for index, url in enumerate(URL_TOKENS * 4):
        add("url_token", f"Link that leaked: {url}", url)

    # ---- person names (model pass) --------------------------------------
    person_templates = [
        "{n} signed off on the design yesterday.",
        "We need {n} to confirm the numbers.",
        "Waiting on {n} for the final call.",
        "{n} flagged the regression first.",
    ]
    for index, name in enumerate(PERSON_NAMES * 2):
        add("person_name", person_templates[index % 4].format(n=name), name)

    # ---- client names ----------------------------------------------------
    client_templates = [
        "The invoice for {c} is still unpaid.",
        "{c} wants the dashboard by Friday.",
    ]
    for index, client in enumerate(CLIENT_NAMES * 2):
        add("client_name", client_templates[index % 2].format(c=client), client)

    # ---- project names ---------------------------------------------------
    for index, project in enumerate(PROJECT_NAMES * 2):
        add("project_name", f"{project} is still not announced, keep it quiet.", project)

    # ---- financial -------------------------------------------------------
    for index, amount in enumerate(FINANCIAL * 2):
        add("financial", f"The client approved {amount} for the next phase.", amount)

    # ---- health ----------------------------------------------------------
    for index, health in enumerate(HEALTH * 2):
        add("health", f"Private note: {health}.", health)

    rng.shuffle(items)
    for index, item in enumerate(items, start=1):
        item["id"] = f"rb-{index:04d}"
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--seed", type=int, default=20261023)
    args = parser.parse_args(argv)
    items = build(seed=args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    counts: dict[str, int] = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    print(f"wrote {len(items)} labelled items to {out}")
    for category, count in sorted(counts.items()):
        print(f"  {category:<14}{count:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
