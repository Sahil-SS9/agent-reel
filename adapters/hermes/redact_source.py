"""Hermes' redaction patterns, composed for the core.

The pattern *content* (56 vendor token prefixes and the secret-name
vocabularies) is lifted verbatim from Hermes `agent/redact.py` at the commit the
pack pinned, via `scripts/extract_hermes_redact.py`. The composing regexes below
are written here so the core never imports Hermes (decision D2) and so each rule
is testable on its own.

When the adapter genuinely runs inside Hermes, `hermes_available()` reports it and
callers may use Hermes' own `redact_text` instead; outside Hermes the snapshot is
the source of truth.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from canon.redact import Rule

SNAPSHOT = Path(__file__).with_name("hermes_redact_patterns.json")


def hermes_available() -> bool:
    """True when this process is inside a Hermes install with agent.redact."""
    try:  # pragma: no cover - depends on the host
        import agent.redact  # noqa: F401
    except Exception:
        return False
    return True


def load_snapshot(path: Path | str = SNAPSHOT) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rules_from_snapshot(snapshot: dict | None = None) -> tuple[Rule, ...]:
    snap = snapshot if snapshot is not None else load_snapshot()
    rules: list[Rule] = []

    # ---- secrets: vendor token prefixes (verbatim from Hermes) -----------
    # Hermes' patterns carry no left boundary, so "sk-" also matches inside an
    # ordinary identifier ("kanban-blocked-task-resolution"). Requiring a token
    # boundary keeps real keys ("Bearer sk-proj-...") and stops the false positive.
    for index, prefix in enumerate(snap["prefix_patterns"]):
        rules.append(
            Rule(
                "secret",
                f"hermes_prefix_{index}",
                re.compile(rf"(?<![A-Za-z0-9_\-])(?:{prefix})"),
            )
        )

    # ---- secrets: credentials in assignments and headers -----------------
    env_names = snap["secret_env_names"]
    cfg_names = snap["secret_cfg_names"]
    yaml_names = snap["yaml_cfg_names"]
    json_keys = snap["json_key_names"]
    header_names = "|".join(re.escape(name) for name in snap["secret_header_names"])

    rules.extend(
        [
            Rule(
                "secret",
                "hermes_env_assign",
                re.compile(rf"([A-Za-z0-9_]{{0,50}}{env_names}[A-Za-z0-9_]{{0,50}})\s*=\s*['\"]?(\S+)"),
            ),
            Rule(
                "secret",
                "hermes_cfg_assign",
                re.compile(rf"(?i)({cfg_names})\s*[:=]\s*['\"]?([^\s&'\"]+)"),
            ),
            Rule(
                "secret",
                "hermes_yaml_assign",
                re.compile(rf"(?im)^\s*({yaml_names})\s*:\s*['\"]?([^\s#'\"]+)"),
            ),
            Rule(
                "secret",
                "hermes_json_field",
                re.compile(rf'(?i)("{json_keys}")\s*:\s*"([^"]+)"'),
            ),
            Rule(
                "secret",
                "hermes_auth_header",
                re.compile(r"(?i)((?:proxy-)?authorization:\s*)([^\s\"']+)"),
            ),
            Rule("secret", "hermes_secret_header", re.compile(rf"(?i)((?:{header_names})\s*:\s*)(\S+)")),
            Rule("secret", "private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
            # A bare header is already a leak (held-out case ho-14).
            Rule("secret", "private_key_header", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
            # A keyword followed straight by an opaque value: "the webhook token X was
            # pasted into the ticket" (held-out case ho-11).
            Rule(
                "secret",
                "keyword_token",
                re.compile(
                    r"(?i)\b(?:webhook|bot|api|access|refresh|session|auth|bearer|signing)?"
                    r"\s?token\s+['\"]?[A-Za-z0-9_\-]{18,}"
                ),
            ),
            Rule("secret", "bearer_token", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-]{12,})")),
            Rule("secret", "jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
            Rule("secret", "telegram_bot_token", re.compile(r"(?<!\d)(?:bot)?(\d{8,}):([-A-Za-z0-9_]{30,})")),
            Rule("secret", "aws_secret", re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*([A-Za-z0-9/+=]{20,})")),
            Rule("secret", "basic_auth_url", re.compile(r"[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@[^\s/]+")),
        ]
    )

    # ---- pii -------------------------------------------------------------
    rules.extend(
        [
            Rule("email", "email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
            # Trailing punctuation must be allowed: a phone or IP at the end of a
            # sentence is the common case. ``(?!\.\d)`` still rejects matching
            # three segments of a longer dotted string.
            Rule(
                "phone",
                "phone_uk",
                re.compile(r"(?<![\w.])(?:\+44\s?7\d{3}|07\d{3})\s?\d{3}\s?\d{3}(?![\w])(?!\.\d)"),
            ),
            # UK landlines: "020 7946 0958", "0161 496 0000" (held-out case ho-20).
            Rule(
                "phone",
                "phone_uk_landline",
                re.compile(
                    r"(?<![\w.])0(?:1\d{2,3}|20)\s?\d{3,4}\s?\d{3,4}(?![\w])(?!\.\d)"
                ),
            ),
            Rule(
                "phone",
                "phone_intl",
                re.compile(
                    r"(?<![\w.])\+\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}"
                    r"[\s\-]?\d{3,4}(?![\w])(?!\.\d)"
                ),
            ),
            Rule(
                "ip",
                "ipv4",
                re.compile(
                    r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
                    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w])(?!\.\d)"
                ),
            ),
            Rule("path", "abs_home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]+(?:/[^\s\"'`,;)]*)?")),
            Rule("path", "abs_private_path", re.compile(r"/(?:private|var/folders|root)/[^\s\"'`,;)]+")),
            # Audit M1-F3: a token in a URL *path* is a secret. Discord webhooks are
            # the live case on this fleet; Slack and generic opaque path segments are
            # the same shape.
            Rule(
                "secret",
                "discord_webhook",
                re.compile(
                    r"https?://(?:[\w.-]+\.)?discord(?:app)?\.com/api/webhooks/"
                    r"\d{6,}/[A-Za-z0-9_\-]{20,}"
                ),
            ),
            Rule(
                "secret",
                "webhook_path",
                re.compile(r"/(?:api/)?webhooks?/\d{6,}/[A-Za-z0-9_\-]{20,}"),
            ),
            Rule(
                "secret",
                "slack_webhook",
                re.compile(r"https?://hooks\.slack\.com/services/[A-Za-z0-9/_\-]{20,}"),
            ),
            Rule(
                "secret",
                "url_path_token",
                # A long, opaque path segment: session ids and signed path tokens.
                re.compile(
                    r"(?<=/)[A-Za-z0-9_\-]{28,}"
                    r"(?=[/?#\s\"'<>]|$)"
                ),
            ),
            Rule(
                "secret",
                "plain_credential",
                # "the password is X", "my api key was X", "token: X".
                re.compile(
                    r"(?i)\b(?:the\s+|my\s+|our\s+)?"
                    r"(?:password|passphrase|passcode|pass\s?word|token|api[\s_-]?key|"
                    r"secret|pin)\s+(?:is|was|=|:)\s*['\"]?[^\s'\"]{3,}"
                ),
            ),
            Rule(
                "url_token",
                "signed_url",
                re.compile(
                    r"(?i)https?://[^\s\"'<>]*[?&](?:token|key|sig|signature|auth|access_token|api_key|x-amz-[a-z]+)=[^\s&\"'<>]+"
                ),
            ),
            # Card and NHS numbers are only recognised in their *written* form
            # (grouped digits). A bare 10- or 16-digit run is far more likely to be
            # an epoch timestamp, a count or an id, and over-matching those would
            # wreck both the story and any reader's trust in the gate.
            Rule("financial", "card_number", re.compile(r"(?<![\d.])(?:\d{4}[ \-]){3}\d{4}(?![\d.])")),
            Rule("financial", "iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
            Rule("health", "nhs_number", re.compile(r"(?<![\d.])\d{3}[ \-]\d{3}[ \-]\d{4}(?![\d.])")),
        ]
    )
    return tuple(rules)


#: Category labels that count as "hard secrets" for the benchmark gate.
SECRET_CATEGORIES = frozenset({"secret"})


#: Public mode always masks these (round 5, R4-F6, decision D13). The private mode is
#: unchanged: the owner's own history keeps its plain money figures.
_PUBLIC_RULES = (
    Rule("financial", "money", re.compile(r"(?:[$\u00a3\u20ac]\s?\d[\d,]*(?:\.\d+)?)")),
    Rule(
        "financial",
        "money_word",
        re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:usd|gbp|eur|dollars?|pounds?|euros?)\b", re.I),
    ),
    Rule("health", "nhs_number", re.compile(r"(?<![\d.])\d{3}[ \-]\d{3}[ \-]\d{4}(?![\d.])")),
)


def public_rules() -> tuple[Rule, ...]:
    """Extra deterministic rules applied only in public mode."""
    return _PUBLIC_RULES
