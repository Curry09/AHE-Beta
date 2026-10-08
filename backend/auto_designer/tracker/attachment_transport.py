"""Spec-0070/T1: explicit formats and the fixed Gitea.com signed-download boundary."""

import re
from urllib.parse import urlsplit

import requests

MIME_TYPES = {"gzip": "application/gzip", "zip": "application/zip"}
_R2 = re.compile(r"[a-f0-9]{32}\.r2\.cloudflarestorage\.com")


def allows_encoding(allowed_types: str | None, encoding: str) -> bool:
    """Interpret Gitea's extensions/MIME rules against the actual upload MIME."""
    if encoding not in MIME_TYPES:
        raise ValueError("unknown observation encoding")
    rules = {
        item.strip().lower().split(";", 1)[0].strip() for item in (allowed_types or "").split(",")
    }
    if not rules - {""} or "*/*" in rules:
        return True
    names = {MIME_TYPES[encoding], ".gz" if encoding == "gzip" else ".zip", "application/*"}
    if encoding == "gzip":
        names.add("application/x-gzip")
    return bool(rules & names)


def download_policy(base_url: str) -> str:
    parsed = urlsplit(base_url)
    try:
        hosted = (
            parsed.scheme == "https"
            and parsed.hostname == "gitea.com"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and "?" not in base_url
            and "#" not in base_url
        )
    except ValueError:
        hosted = False
    return "gitea-com-r2-v1" if hosted else "same-origin-v1"


def validate_r2_location(location: str) -> str:
    """Never include the supplied signed URL in an error message."""
    try:
        parsed = urlsplit(location)
        valid = (
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and "#" not in location
            and _R2.fullmatch(parsed.hostname or "")
            and not any(ch.isspace() or ord(ch) < 32 for ch in location)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("observation attachment redirect target is not permitted")
    return location


def anonymous_session(source, url: str):
    """A clean session: no Gitea headers/cookies/netrc, retaining network proxies."""
    session = requests.Session()
    session.trust_env = False
    session.proxies.update(requests.utils.get_environ_proxies(url))
    session.proxies.update(getattr(source, "proxies", {}) or {})
    return session
