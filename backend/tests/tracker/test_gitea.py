"""spec-0002/T2：GiteaTracker 单测，全程 mock HTTP，不依赖运行中的 Gitea。"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from ahe_beta.models import IssueDraft
from ahe_beta.tracker.base import IdempotencyConflictError, IssueTracker
from ahe_beta.tracker.gitea import GiteaError, GiteaTracker, IssueMigrationError


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

    def request(
        self,
        method: str,
        url: str,
        json: Any = None,
        timeout: float | None = None,
        allow_redirects: bool = False,
    ) -> _Resp:
        assert timeout is not None, "GiteaTracker 的请求必须带超时（防挂死闭环）"
        assert allow_redirects is False
        self.calls.append((method, url, json))
        return self._handler(method, url, json)

    def post(
        self,
        url: str,
        json: Any = None,
        timeout: float | None = None,
        allow_redirects: bool = False,
    ) -> _Resp:
        return self.request("POST", url, json, timeout=timeout, allow_redirects=allow_redirects)


class FakeGitea:
    """有状态的 mock Gitea 后端：维护 labels / issues，可作为 handler。"""

    def __init__(self, race_on_label: bool = False) -> None:
        self.labels: dict[str, int] = {}
        self._next_label = 1
        self._next_issue = 1
        self.issues: dict[int, dict] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self._race = race_on_label

    def __call__(self, method: str, url: str, json: Any) -> _Resp:
        path = url.split("/api/v1", 1)[1]
        if method == "GET" and path.split("?", 1)[0].endswith("/labels"):
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(url).query)
            page = int(query.get("page", ["1"])[0])
            limit = int(query.get("limit", ["10"])[0])
            start = (page - 1) * limit
            values = [{"id": i, "name": n} for n, i in self.labels.items()]
            return _Resp(200, values[start : start + limit])
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
            self.issues[n] = {
                "number": n,
                "title": json["title"],
                "body": json.get("body", ""),
                "state": "open",
                "labels": json["labels"],
            }
            self.comments[n] = []
            return _Resp(
                201,
                {"number": n, "html_url": f"http://gitea/issues/{n}", "state": "open"},
            )
        if method == "POST" and path.endswith("/comments"):
            n = int(path.rsplit("/", 2)[1])
            comment = {"id": len(self.comments[n]) + 1, "body": json["body"], "user": {}}
            self.comments[n].append(comment)
            return _Resp(201, comment)
        if method == "GET" and path.endswith("/comments"):
            n = int(path.rsplit("/", 2)[1])
            return _Resp(200, list(self.comments[n]))
        if method == "GET" and "/issues?" in path:
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(url).query)
            page = int(query.get("page", ["1"])[0])
            limit = int(query.get("limit", ["50"])[0])
            values = []
            by_id = {label_id: name for name, label_id in self.labels.items()}
            for issue in self.issues.values():
                item = dict(issue)
                item["html_url"] = f"http://gitea/issues/{item['number']}"
                item["labels"] = [
                    {"id": label_id, "name": by_id[label_id]} for label_id in item["labels"]
                ]
                values.append(item)
            start = (page - 1) * limit
            return _Resp(200, values[start : start + limit])
        if method == "GET" and "/issues/" in path:
            n = int(path.rsplit("/", 1)[1])
            issue = dict(self.issues[n])
            by_id = {label_id: name for name, label_id in self.labels.items()}
            issue["labels"] = [
                {"id": label_id, "name": by_id[label_id]} for label_id in issue["labels"]
            ]
            return _Resp(200, issue)
        if method == "PATCH" and "/issues/" in path:
            n = int(path.rsplit("/", 1)[1])
            # Gitea 1.22 EditIssueOption 不含 labels；未知字段被忽略。
            accepted = {
                key: value for key, value in json.items() if key in {"title", "body", "state"}
            }
            self.issues[n].update(accepted)
            return _Resp(200, {"number": n, **accepted})
        if method == "PUT" and path.endswith("/labels"):  # Spec-0025/T3a：整组替换
            n = int(path.rsplit("/", 2)[1])
            self.issues[n]["labels"] = json["labels"]
            return _Resp(200, {"number": n})
        return _Resp(404, text=f"no route {method} {path}")


def _tracker(handler) -> GiteaTracker:
    t = GiteaTracker(base_url="http://gitea/", owner="o", repo="r", token="T")
    t._session = _FakeSession(handler)
    return t


def test_satisfies_protocol() -> None:
    assert isinstance(_tracker(FakeGitea()), IssueTracker)


@pytest.mark.parametrize("count", [0, 50, 117])
def test_open_issue_queue_reads_every_page(count) -> None:
    from urllib.parse import parse_qs, urlparse

    issues = [
        {"number": number, "title": str(number), "labels": [{"name": "proposal"}]}
        for number in range(1, count + 1)
    ]
    pages = []

    def handler(method, url, body):
        query = parse_qs(urlparse(url).query)
        assert method == "GET" and body is None
        assert query["state"] == ["open"] and query["type"] == ["issues"]
        page = int(query["page"][0])
        pages.append(page)
        return _Resp(200, issues[(page - 1) * 50 : page * 50])

    observed = _tracker(handler).list_open_issues()
    assert [issue.number for issue in observed] == list(range(1, count + 1))
    assert pages == list(range(1, count // 50 + 2))


def test_open_issue_queue_does_not_return_partial_data_on_later_page_error() -> None:
    def handler(method, url, body):
        if "page=1" in url:
            return _Resp(200, [{"number": number} for number in range(1, 51)])
        return _Resp(503, text="temporarily unavailable")

    with pytest.raises(GiteaError):
        _tracker(handler).list_open_issues()


def test_authorization_header_set() -> None:
    t = GiteaTracker(base_url="http://gitea", owner="o", repo="r", token="SECRET")
    assert t._session.headers["Authorization"] == "token SECRET"
    assert t._api == "http://gitea/api/v1"  # base_url 去尾斜杠 + /api/v1


def test_session_is_thread_local_with_injectable_override() -> None:
    """Spec-0017/T6：requests.Session 非线程安全 → 每线程独立会话；注入 override 全线程共用。

    并行 a 段各会话线程收尾并发 create_issue：每线程必须拿到自己的 Session（各带全 header、
    同线程复用同一实例）；测试的 `t._session = fake` 注入语义保持不变（setter 存 override）。
    """
    import threading

    t = GiteaTracker(base_url="http://gitea", owner="o", repo="r", token="SECRET")
    grabbed: dict[str, object] = {}

    def grab(key: str) -> None:
        first = t._session
        grabbed[key] = first
        assert t._session is first  # 同线程复用同一实例

    for key in ("a", "b"):
        th = threading.Thread(target=grab, args=(key,))
        th.start()
        th.join()
    main = t._session
    assert grabbed["a"] is not grabbed["b"]  # 各线程独立
    assert grabbed["a"] is not main and grabbed["b"] is not main
    for s in (grabbed["a"], grabbed["b"], main):
        assert s.headers["Authorization"] == "token SECRET"  # 每线程都带全 header

    fake = _FakeSession(FakeGitea())
    t._session = fake  # 测试注入：override 覆盖所有线程
    assert t._session is fake
    result: list[object] = []
    th = threading.Thread(target=lambda: result.append(t._session))
    th.start()
    th.join()
    assert result[0] is fake


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


def test_create_issue_once_reconciles_remote_marker() -> None:
    backend = FakeGitea()
    backend.labels = {"bug": 5}
    tracker = _tracker(backend)
    draft = IssueDraft(title="t", body="b", labels=["bug"])
    first = tracker.create_issue_once(draft, operation_key="round-1/user-1/report-1")
    second = tracker.create_issue_once(draft, operation_key="round-1/user-1/report-1")
    assert first == second
    assert len(backend.issues) == 1
    with pytest.raises(IdempotencyConflictError):
        tracker.create_issue_once(
            IssueDraft(title="changed", body="b", labels=["bug"]),
            operation_key="round-1/user-1/report-1",
        )


def test_add_comment_once_reconciles_remote_marker() -> None:
    backend = FakeGitea()
    tracker = _tracker(backend)
    issue = tracker.create_issue(IssueDraft(title="t", body="b"))
    tracker.add_comment_once(issue.number, "decision", operation_key="owner/1")
    tracker.add_comment_once(issue.number, "decision", operation_key="owner/1")
    assert len(backend.comments[issue.number]) == 1
    with pytest.raises(IdempotencyConflictError):
        tracker.add_comment_once(issue.number, "changed", operation_key="owner/1")


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


def test_existing_label_on_later_page_is_not_recreated() -> None:
    backend = FakeGitea()
    backend.labels = {f"label-{n}": n + 1 for n in range(117)}
    tracker = _tracker(backend)
    issue = tracker.create_issue(IssueDraft("later page", "body", ["label-116"]))
    assert backend.issues[issue.number]["labels"] == [117]
    assert not any(
        method == "POST" and url.endswith("/labels") for method, url, _ in tracker._session.calls
    )


def test_duplicate_label_names_use_one_id_per_requested_name() -> None:
    def handler(method, url, body):
        if method == "GET":
            return _Resp(200, [{"id": 7, "name": "ready"}, {"id": 9, "name": "ready"}])
        assert method == "PUT" and body == {"labels": [7]}
        return _Resp(200, {})

    tracker = _tracker(handler)
    tracker.set_labels(1, ["ready", "ready"])


def test_label_server_repeating_full_page_does_not_loop() -> None:
    rows = [{"id": n + 1, "name": f"label-{n}"} for n in range(50)]

    def handler(method, url, body):
        assert method == "GET"
        return _Resp(200, rows)

    tracker = _tracker(handler)
    tracker.ensure_labels(["label-49"])
    assert len(tracker._session.calls) == 2


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


def test_update_issue_uses_edit_then_label_endpoint() -> None:
    backend = FakeGitea()
    backend.labels = {"proposal": 7}
    t = _tracker(backend)
    ref = t.create_issue(IssueDraft(title="raw", body="raw"))
    t.update_issue(ref.number, title="normalized", body="fields", labels=["proposal"])
    patches = [call for call in t._session.calls if call[0] == "PATCH"]
    assert patches[-1][2] == {"title": "normalized", "body": "fields"}
    label_puts = [call for call in t._session.calls if call[0] == "PUT"]
    assert label_puts[-1][2] == {"labels": [7]}
    assert backend.issues[ref.number]["labels"] == [7]


def test_transition_issue_uses_label_endpoint_then_state_patch() -> None:
    backend = FakeGitea()
    backend.labels = {"declined": 9}
    t = _tracker(backend)
    ref = t.create_issue(IssueDraft(title="t", body="b"))
    t.transition_issue(ref.number, state="closed", labels=["declined"])
    patch = [call for call in t._session.calls if call[0] == "PATCH"][-1]
    assert patch[2] == {"state": "closed"}
    label_put = [call for call in t._session.calls if call[0] == "PUT"][-1]
    assert label_put[2] == {"labels": [9]}


def test_update_issue_rolls_back_body_when_label_update_fails() -> None:
    class FailFirstLabelPut(FakeGitea):
        failed = False

        def __call__(self, method: str, url: str, json: Any) -> _Resp:
            path = url.split("/api/v1", 1)[1]
            if method == "PUT" and path.endswith("/labels") and not self.failed:
                self.failed = True
                return _Resp(500, text="label write failed")
            return super().__call__(method, url, json)

    backend = FailFirstLabelPut()
    backend.labels = {"report": 1, "proposal": 2}
    tracker = _tracker(backend)
    ref = tracker.create_issue(IssueDraft(title="raw title", body="raw body", labels=["report"]))

    with pytest.raises(IssueMigrationError, match="label write failed"):
        tracker.update_issue(
            ref.number,
            title="normalized title",
            body="normalized body",
            labels=["proposal"],
        )

    assert backend.issues[ref.number] == {
        "number": ref.number,
        "title": "raw title",
        "body": "raw body",
        "state": "open",
        "labels": [1],
    }


def test_transition_issue_rolls_back_labels_when_state_update_fails() -> None:
    class FailFirstStatePatch(FakeGitea):
        failed = False

        def __call__(self, method: str, url: str, json: Any) -> _Resp:
            path = url.split("/api/v1", 1)[1]
            if (
                method == "PATCH"
                and "/issues/" in path
                and json == {"state": "closed"}
                and not self.failed
            ):
                self.failed = True
                return _Resp(500, text="state write failed")
            return super().__call__(method, url, json)

    backend = FailFirstStatePatch()
    backend.labels = {"proposal": 1, "merged": 2}
    tracker = _tracker(backend)
    ref = tracker.create_issue(IssueDraft(title="proposal", body="body", labels=["proposal"]))

    with pytest.raises(IssueMigrationError, match="state write failed"):
        tracker.transition_issue(ref.number, state="closed", labels=["merged"])

    assert backend.issues[ref.number]["state"] == "open"
    assert backend.issues[ref.number]["labels"] == [1]


def test_update_issue_verifies_postcondition_when_backend_silently_ignores_labels() -> None:
    class IgnoreLabelPut(FakeGitea):
        def __call__(self, method: str, url: str, json: Any) -> _Resp:
            path = url.split("/api/v1", 1)[1]
            if method == "PUT" and path.endswith("/labels"):
                return _Resp(200, {"number": 1})
            return super().__call__(method, url, json)

    backend = IgnoreLabelPut()
    backend.labels = {"report": 1, "proposal": 2}
    tracker = _tracker(backend)
    ref = tracker.create_issue(IssueDraft(title="raw", body="evidence", labels=["report"]))

    with pytest.raises(IssueMigrationError) as caught:
        tracker.update_issue(ref.number, title="normalized", body="fields", labels=["proposal"])

    assert caught.value.number == ref.number
    assert caught.value.operation == "update_issue"
    assert caught.value.observed is not None
    assert backend.issues[ref.number]["title"] == "raw"
    assert backend.issues[ref.number]["body"] == "evidence"


def test_set_state_illegal_value() -> None:
    t = _tracker(FakeGitea())
    with pytest.raises(ValueError):
        t.set_state(1, "merged", "x")


def test_set_labels_replaces_via_put() -> None:
    """Spec-0025/T3a：整组替换——ensure 缺失标签拿 id → PUT labels（替换语义）。"""
    backend = FakeGitea()
    backend.labels = {"bug": 5, "needs-triage": 6}
    t = _tracker(backend)
    ref = t.create_issue(IssueDraft(title="t", body="b", labels=["bug", "needs-triage"]))
    # triage 完成：去 needs-triage、加 triaged（triaged 是新标签 → 先 ensure）
    t.set_labels(ref.number, ["bug", "triaged"])
    put = [c for c in t._session.calls if c[0] == "PUT" and c[1].endswith("/labels")]
    assert len(put) == 1
    assert put[0][2] == {"labels": [backend.labels["bug"], backend.labels["triaged"]]}
    assert backend.issues[ref.number]["labels"] == [
        backend.labels["bug"],
        backend.labels["triaged"],
    ]
    assert "triaged" in backend.labels  # 新标签被 ensure 建出


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


def test_transient_get_server_error_retries_without_replaying_writes(monkeypatch) -> None:
    monkeypatch.setattr("ahe_beta.tracker.gitea.time.sleep", lambda _seconds: None)
    calls: list[str] = []

    def handler(method: str, url: str, json: Any) -> _Resp:
        calls.append(method)
        if method == "GET" and calls.count("GET") < 3:
            return _Resp(502, text="temporary gateway failure")
        if method == "POST":
            return _Resp(502, text="write result unknown")
        return _Resp(200, [])

    tracker = _tracker(handler)
    assert tracker._request("GET", "/repos/o/r/labels", None) == []
    assert calls == ["GET", "GET", "GET"]
    with pytest.raises(GiteaError) as exc:
        tracker._request("POST", "/repos/o/r/issues", {})
    assert exc.value.status == 502
    assert calls == ["GET", "GET", "GET", "POST"]


def test_connection_error_propagates() -> None:
    def boom(method: str, url: str, json: Any) -> _Resp:
        raise requests.ConnectionError("unreachable")

    t = _tracker(boom)
    with pytest.raises(requests.ConnectionError):
        t.create_issue(IssueDraft(title="t", body="b"))
