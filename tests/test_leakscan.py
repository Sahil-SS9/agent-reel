"""The evidence pre-flight leak scan."""

from __future__ import annotations

from adapters.hermes.leakscan import scan_lines, scan_text


def test_clean_text_has_no_hits():
    lines = [
        "Hermes Scrollback Reel \u2014 history summary",
        "window: 2026-10-16T00:00:00+00:00 .. 2026-10-23T00:00:00+00:00 (7.00 days)",
        "message       131,204",
        "2026-10-23T09:54  default  cli  Execute the M0 handoff",
    ]
    assert scan_lines(lines) == []


def test_email_and_phone_are_flagged():
    hits = scan_text("contact sahil@example.com or +44 7700 900123")
    assert {hit.pattern for hit in hits} >= {"email", "phone"}


def test_provider_tokens_are_flagged():
    hits = scan_text("key sk-abcdef0123456789abcdef0123456789 leaked")
    assert any(hit.pattern == "provider_token" for hit in hits)


def test_private_key_is_flagged():
    hits = scan_text("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert any(hit.pattern == "private_key" for hit in hits)


def test_home_path_is_flagged():
    hits = scan_text("config lives at /home/kensei/.hermes/config.yaml")
    assert any(hit.pattern == "home_path" for hit in hits)


def test_ipv4_is_flagged_but_version_strings_are_not():
    hits = scan_text("host 192.168.1.24 answered")
    assert any(hit.pattern == "ipv4" for hit in hits)
    assert not scan_text("Hermes Agent v0.22.2+4106.g513ab22 (2026.9.24)")


def test_high_entropy_token_is_flagged():
    token = "Xk9fQ2mLp7Rt4Vb8Nw1Zs6Yh3Jc5Gd0Aq"
    hits = scan_text(f"blob {token} end")
    assert any(hit.pattern in {"high_entropy", "provider_token"} for hit in hits)


def test_ordinary_prose_is_not_flagged_as_high_entropy():
    assert scan_text("the quick brown fox jumps over the lazy dog repeatedly") == []


def test_line_numbers_are_reported():
    hits = scan_text("clean\nclean\nsecret@example.com", first_line=10)
    assert hits[0].line == 12
