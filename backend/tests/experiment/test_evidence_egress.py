"""Hosted egress must remain opt-in and match destinations, not arbitrary URLs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


@pytest.mark.parametrize("deployment", ["gitea", "experiment"])
def test_hosted_config_preserves_default_policy(deployment: str) -> None:
    root = DEPLOY / deployment
    compose = (root / "docker-compose.yml").read_text()
    default = (root / "egress-proxy.conf").read_text()
    hosted = (root / "egress-gitea-com.conf").read_text()
    assert "${AHE_BETA_EGRESS_CONFIG:-./egress-proxy.conf}:/etc/squid/squid.conf:ro" in compose
    assert "./egress-proxy.conf:/etc/squid/egress-base.conf:ro" in compose
    assert "include /etc/squid/egress-base.conf" in hosted
    assert "http_access deny all" in default
    assert "evidence_gitea" not in default
    assert "evidence_r2" not in default
    assert "acl evidence_connect method CONNECT" in hosted
    assert "acl evidence_tls_port port 443" in hosted
    assert "acl evidence_gitea dstdomain -n gitea.com" in hosted
    assert "url_regex" not in hosted
    allow_rules = [line for line in hosted.splitlines() if line.startswith("http_access")]
    assert allow_rules == [
        "http_access allow evidence_connect evidence_tls_port evidence_gitea",
        "http_access allow evidence_connect evidence_tls_port evidence_r2",
    ]


@pytest.mark.parametrize("deployment", ["gitea", "experiment"])
@pytest.mark.parametrize(
    "hostname,allowed",
    [
        ("a" * 32 + ".r2.cloudflarestorage.com", True),
        ("0123456789abcdef" * 2 + ".r2.cloudflarestorage.com", True),
        ("a" * 31 + ".r2.cloudflarestorage.com", False),
        ("g" * 32 + ".r2.cloudflarestorage.com", False),
        ("a" * 32 + ".r2.cloudflarestorage.com.evil.test", False),
        ("prefix." + "a" * 32 + ".r2.cloudflarestorage.com", False),
        ("https://" + "a" * 32 + ".r2.cloudflarestorage.com", False),
        ("evil.test/?target=" + "a" * 32 + ".r2.cloudflarestorage.com", False),
        ("127.0.0.1", False),
    ],
)
def test_r2_acl_is_a_whole_destination_match(deployment: str, hostname: str, allowed: bool) -> None:
    hosted = (DEPLOY / deployment / "egress-gitea-com.conf").read_text()
    rule = next(line for line in hosted.splitlines() if line.startswith("acl evidence_r2 "))
    # Check the actual deployed pattern; -n also prohibits IP reverse-lookup matches.
    assert rule.startswith("acl evidence_r2 dstdom_regex -n ")
    pattern = rule.split(" -n ", 1)[1]
    assert bool(re.search(pattern, hostname)) is allowed
