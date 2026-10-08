import io
from types import SimpleNamespace

import pytest

from auto_designer.observations.transport import make_transport_profile
from auto_designer.tracker.attachment_transport import (
    allows_encoding,
    anonymous_session,
    download_policy,
    validate_r2_location,
)
from auto_designer.tracker.gitea import GiteaError, GiteaTracker

R2 = "https://" + "a" * 32 + ".r2.cloudflarestorage.com/object?signature=secret"


@pytest.mark.parametrize(
    "rules,gzip,zip_",
    [
        (".GZ,.ZIP", True, True),
        ("application/gzip; charset=x", True, False),
        ("application/x-gzip", True, False),
        ("image/*,.zip,application/octet-stream,text/plain", False, True),
        ("", True, True),
        ("*/*", True, True),
        (".gzip", False, False),
    ],
)
def test_format_rules(rules, gzip, zip_):
    assert allows_encoding(rules, "gzip") is gzip
    assert allows_encoding(rules, "zip") is zip_


@pytest.mark.parametrize(
    "url",
    [
        "http://gitea.com",
        "https://gitea.com.evil",
        "https://gitea.com/base",
        "https://user@gitea.com",
        "https://gitea.com:444",
    ],
)
def test_hosted_policy_origin_is_exact(url):
    assert download_policy(url) == "same-origin-v1"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/object",
        R2.replace("https:", "http:"),
        R2.replace(".com/", ".com:444/"),
        R2 + "#fragment",
        R2.replace("https://", "https://user@"),
        R2.replace("a" * 32, "a" * 31),
        "https://127.0.0.1/file",
    ],
)
def test_reject_external_targets_without_echoing_url(url):
    with pytest.raises(ValueError) as error:
        validate_r2_location(url)
    assert "signature" not in str(error.value)


class Response:
    def __init__(self, code=200, body=b"payload", location=None):
        self.status_code = code
        self.raw = SimpleNamespace(read1=lambda size, **kw: self.stream.read(size))
        self.stream = io.BytesIO(body)
        self.headers = {"Location": location} if location else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def tracker(host="https://gitea.com"):
    obj = GiteaTracker(host, "o", "r", "private-token")
    profile = make_transport_profile(
        repository=obj._api + "/repos/o/r", encoding="zip", download_policy="gitea-com-r2-v1"
    )
    obj.bind_observation_transport(profile=profile, reader_verified=True)
    return obj


def test_hosted_selection_does_not_enable_publication():
    obj = GiteaTracker("https://gitea.com", "o", "r", "token")
    obj._request = lambda method, endpoint, payload: (
        {
            "enabled": True,
            "max_size": 1024,
            "allowed_types": "image/*,.zip,application/octet-stream,text/plain",
        }
        if endpoint == "/settings/attachment"
        else {"permissions": {"push": True}}
    )
    profile = obj.select_observation_transport()
    assert profile["encoding"] == "zip"
    assert obj.observation_transport is None
    with pytest.raises(ValueError, match="verified reader"):
        obj.bind_observation_transport(profile=profile)
    with pytest.raises(ValueError):
        obj.preflight_observations()
    obj.bind_observation_transport(profile=profile, reader_verified=True)
    assert set(obj.preflight_observations()) == {"repository", "format", "max_transfer_bytes"}


def test_signed_download_and_no_second_hop(monkeypatch):
    from auto_designer.tracker import gitea

    obj = tracker()
    obj._session = SimpleNamespace(get=lambda *a, **kw: Response(303, location=R2))
    external = Response()
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, **kw):
            calls.append((url, kw))
            return external

    monkeypatch.setattr(gitea, "anonymous_session", lambda *a: Session())
    assert (
        obj._observation_bytes(url="https://gitea.com/attachments/id", limit=10, attachment=True)
        == b"payload"
    )
    assert calls[0][1]["allow_redirects"] is False
    external.status_code = 303
    with pytest.raises(GiteaError):
        obj._observation_bytes(url="https://gitea.com/attachments/id", limit=10, attachment=True)
    with pytest.raises(GiteaError):
        obj._observation_bytes(url=obj._api + "/issues", limit=10)


def test_anonymous_session_retains_proxy_not_auth(monkeypatch, tmp_path):
    netrc = tmp_path / "netrc"
    netrc.write_text(
        "machine " + "a" * 32 + ".r2.cloudflarestorage.com login leaked password leaked"
    )
    monkeypatch.setenv("NETRC", str(netrc))
    source = SimpleNamespace(proxies={"https": "http://proxy:3128"})
    with anonymous_session(source, R2) as session:
        import requests

        prepared = session.prepare_request(requests.Request("GET", R2))
        assert "Authorization" not in prepared.headers
        assert "Cookie" not in prepared.headers
        assert session.proxies["https"] == "http://proxy:3128"
        assert session.trust_env is False


def test_download_checks_issue_membership_and_ignores_browser_url():
    obj = GiteaTracker("http://trusted", "o", "r", "token")
    obj.list_issue_assets = lambda **kw: [
        {"id": 1, "uuid": "a" * 36, "browser_download_url": "https://evil.test"}
    ]
    calls = []
    obj._session = SimpleNamespace(get=lambda url, **kw: calls.append(url) or Response())
    assert obj.download_issue_asset(number=2, asset_id=1, limit=20) == b"payload"
    assert calls == ["http://trusted/attachments/" + "a" * 36]
    with pytest.raises(ValueError, match="member"):
        obj.download_issue_asset(number=2, asset_id=999, limit=20)


def test_direct_download_enforces_actual_transfer_size():
    obj = GiteaTracker("http://trusted", "o", "r", "token")
    obj._session = SimpleNamespace(get=lambda *a, **kw: Response(body=b"oversized"))
    with pytest.raises(ValueError, match="budget"):
        obj._observation_bytes(url="http://trusted/attachments/id", limit=4)


def test_redirect_shares_deadline_and_does_not_echo_signature(monkeypatch):
    import requests

    from auto_designer.tracker import gitea

    obj = tracker()
    obj._session = SimpleNamespace(get=lambda *a, **kw: Response(303, location=R2))
    ticks = iter([0, 16])
    monkeypatch.setattr(gitea, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(ValueError, match="budget"):
        obj._observation_bytes(url="https://gitea.com/attachments/id", limit=100, attachment=True)
    monkeypatch.setattr(gitea, "time", SimpleNamespace(monotonic=lambda: 0))

    def failing(*args):
        raise requests.ConnectionError(R2)

    monkeypatch.setattr(gitea, "anonymous_session", failing)
    with pytest.raises(ValueError) as error:
        obj._observation_bytes(url="https://gitea.com/attachments/id", limit=100, attachment=True)
    assert "signature" not in str(error.value)


def test_api_redirect_is_rejected_not_followed():
    obj = GiteaTracker("https://gitea.com", "o", "r", "token")
    calls = []
    obj._session = SimpleNamespace(
        request=lambda *a, **kw: (
            calls.append(kw) or SimpleNamespace(status_code=303, text="redirect")
        )
    )
    with pytest.raises(GiteaError):
        obj._request("GET", "/user", None)
    assert calls[0]["allow_redirects"] is False


def test_auth_failure_does_not_select_zip():
    obj = GiteaTracker("https://gitea.com", "o", "r", "token")

    def fail(*args):
        raise GiteaError(401, "attachment settings")

    obj._request = fail
    with pytest.raises(GiteaError):
        obj.select_observation_transport()
    assert obj.observation_transport is None
