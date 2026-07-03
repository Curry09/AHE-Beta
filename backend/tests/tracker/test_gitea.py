"""spec-0002/T2：GiteaTracker 单测，全程 mock HTTP，不依赖运行中的 Gitea。"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.tracker.gitea import GiteaError, GiteaTracker


class _Resp:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = b"x" if payload is not None else b""

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    """以 handler(method, url, json)->_Resp 驱动；记录所有调用供断言。"""

    def __init__(self, handler) -> None:
        self.headers: dict[str, str] = {}
        self._handler = handler
        self.calls: list[tuple[str, str, Any]] = []

    def request(self, method: str, url: str, json: Any = None, timeout: float | None = None) -> _Resp:
        assert timeout is not None, "GiteaTracker 的请求必须带超时（防挂死闭环）"
        self.calls.append((method, url, json))
        return self._handler(method, url, json)

    def post(self, url: str, json: Any = None, timeout: float | None = None) -> _Resp:
        return self.request("POST", url, json, timeout=timeout)


class FakeGitea:
    """有状态的 mock Gitea 后端：维护 labels / issues，可作为 handler。"""

    def __init__(self, race_on_label: bool = False) -> None:
        self.labels: dict[str, int] = {}
        self._next_label = 1
        self._next_issue = 1
        self.issues: dict[int, dict] = {}
        self._race = race_on_label

    def __call__(self, method: str, url: str, json: Any) -> _Resp:
        path = url.split("/api/v1", 1)[1]
        if method == "GET" and path.endswith("/labels"):
            return _Resp(200, [{"id": i, "name": n} for n, i in self.labels.items()])
        if method == "POST" and path.endswith("/labels"):
            name = json["name"]
            if self._race or name in self.labels:
                if name not in self.labels:  # 模拟他处已建
                    self.labels[name] = self._next_label
                    self._next_label += 1
                return _Resp(409, text="label exists")
            self.labels[name] = self._next_label
            self._next_label += 1
            return _Resp(201, {"id": self.labels[name], "name": name})
        if method == "POST" and path.endswith("/issues"):
            n = self._next_issue
            self._next_issue += 1
            self.issues[n] = {"state": "open", "labels": json["labels"]}
            return _Resp(
                201,
                {"number": n, "html_url": f"http://gitea/issues/{n}", "state": "open"},
            )
        if method == "POST" and path.endswith("/comments"):
            return _Resp(201, {"id": 1})
        if method == "PATCH" and "/issues/" in path:
            n = int(path.rsplit("/", 1)[1])
            self.issues[n]["state"] = json["state"]
            return _Resp(200, {"number": n, "state": json["state"]})
        return _Resp(404, text=f"no route {method} {path}")


def _tracker(handler) -> GiteaTracker:
    t = GiteaTracker(base_url="http://gitea/", owner="o", repo="r", token="T")
    t._session = _FakeSession(handler)
    return t


def test_satisfies_protocol() -> None:
    assert isinstance(_tracker(FakeGitea()), IssueTracker)


def test_authorization_header_set() -> None:
    t = GiteaTracker(base_url="http://gitea", owner="o", repo="r", token="SECRET")
    assert t._session.headers["Authorization"] == "token SECRET"
    assert t._api == "http://gitea/api/v1"  # base_url 去尾斜杠 + /api/v1


def test_create_issue_posts_and_parses_ref() -> None:
    backend = FakeGitea()
    backend.labels = {"bug": 5}
    t = _tracker(backend)
    ref = t.create_issue(IssueDraft(title="t", body="b", labels=["bug"]))
    assert (ref.number, ref.url, ref.state) == (1, "http://gitea/issues/1", "open")
    issue_post = [c for c in t._session.calls if c[0] == "POST" and c[1].endswith("/issues")][0]
    assert issue_post[2] == {"title": "t", "body": "b", "labels": [5]}


def test_create_issue_auto_ensures_missing_label() -> None:
    backend = FakeGitea()  # 无任何预置 label
    t = _tracker(backend)
    ref = t.create_issue(IssueDraft(title="t", body="b", labels=["bug"]))
    assert "bug" in backend.labels
    issue_post = [c for c in t._session.calls if c[0] == "POST" and c[1].endswith("/issues")][0]
    assert issue_post[2]["labels"] == [backend.labels["bug"]]
    assert ref.number == 1


def test_ensure_labels_idempotent() -> None:
    backend = FakeGitea()
    t = _tracker(backend)
    t.ensure_labels(["bug", "feature"])
    t.ensure_labels(["bug", "feature"])
    label_posts = [c for c in t._session.calls if c[0] == "POST" and c[1].endswith("/labels")]
    assert len(label_posts) == 2  # 仅首轮各建一次，第二轮命中缓存/已存在不重复
    assert set(backend.labels) == {"bug", "feature"}


def test_ensure_labels_empty_noop() -> None:
    t = _tracker(FakeGitea())
    t.ensure_labels([])
    assert t._session.calls == []


def test_add_comment_and_set_state() -> None:
    backend = FakeGitea()
    t = _tracker(backend)
    ref = t.create_issue(IssueDraft(title="t", body="b"))
    t.add_comment(ref.number, "一条评论")
    t.set_state(ref.number, "closed", "已修复")
    methods = [(c[0], c[1].split("/api/v1")[1]) for c in t._session.calls]
    assert ("POST", f"/repos/o/r/issues/{ref.number}/comments") in methods
    assert ("PATCH", f"/repos/o/r/issues/{ref.number}") in methods
    assert backend.issues[ref.number]["state"] == "closed"
    # set_state 带 reason 额外发一条 comment
    comment_calls = [c for c in t._session.calls if c[1].endswith("/comments")]
    assert len(comment_calls) == 2


def test_set_state_illegal_value() -> None:
    t = _tracker(FakeGitea())
    with pytest.raises(ValueError):
        t.set_state(1, "merged", "x")


def test_label_race_falls_back_to_get() -> None:
    t = _tracker(FakeGitea(race_on_label=True))  # POST label 恒 409
    t.ensure_labels(["bug"])
    assert t._label_ids.get("bug") is not None  # 回退 GET 取到 id，ensure 仍成功


def test_non_2xx_raises_with_status() -> None:
    def unauthorized(method: str, url: str, json: Any) -> _Resp:
        if url.endswith("/labels") and method == "GET":
            return _Resp(200, [])
        return _Resp(401, text="bad token")

    t = _tracker(unauthorized)
    with pytest.raises(GiteaError) as ei:
        t.create_issue(IssueDraft(title="t", body="b"))
    assert ei.value.status == 401


def test_connection_error_propagates() -> None:
    def boom(method: str, url: str, json: Any) -> _Resp:
        raise requests.ConnectionError("unreachable")

    t = _tracker(boom)
    with pytest.raises(requests.ConnectionError):
        t.create_issue(IssueDraft(title="t", body="b"))
