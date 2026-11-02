"""GiteaTracker 观测读路径单测：全状态 issue / 单条 issue / 评论 / commit 详情（mock HTTP）。"""

from __future__ import annotations

from typing import Any

import pytest

from ahe_beta.tracker.gitea import GiteaError, GiteaTracker


class _Resp:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = b"x" if payload is not None or text else b""

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, handler) -> None:
        self.headers: dict[str, str] = {}
        self._handler = handler
        self.calls: list[tuple[str, str]] = []

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
        self.calls.append((method, url))
        return self._handler(method, url, json)


def _tracker(handler) -> GiteaTracker:
    t = GiteaTracker(base_url="http://gitea", owner="o", repo="r", token="T")
    t._session = _FakeSession(handler)
    return t


_ISSUE_RAW = {
    "number": 7,
    "title": "harness 卡顿",
    "body": "复现步骤……",
    "labels": [{"name": "bug"}, {"name": "design"}],
    "state": "closed",
    "created_at": "2026-07-01T10:00:00Z",
    "closed_at": "2026-07-02T09:00:00Z",
    "html_url": "http://gitea/o/r/issues/7",
}


def test_list_issues_all_states_full_fields() -> None:
    def handler(method: str, url: str, json: Any) -> _Resp:
        assert "state=all" in url and "type=issues" in url
        return _Resp(200, [_ISSUE_RAW])

    (issue,) = _tracker(handler).list_issues()
    assert issue == {
        "number": 7,
        "title": "harness 卡顿",
        "body": "复现步骤……",
        "labels": ["bug", "design"],
        "state": "closed",
        "created_at": "2026-07-01T10:00:00Z",
        "closed_at": "2026-07-02T09:00:00Z",
        "url": "http://gitea/o/r/issues/7",
    }


def test_get_issue_and_comments() -> None:
    def handler(method: str, url: str, json: Any) -> _Resp:
        if url.endswith("/issues/7/comments"):
            return _Resp(
                200,
                [
                    {
                        "user": {"login": "developer"},
                        "body": "已推进 main v2",
                        "created_at": "2026-07-02T09:00:00Z",
                    }
                ],
            )
        if url.endswith("/issues/7"):
            return _Resp(200, _ISSUE_RAW)
        return _Resp(404, text="no route")

    t = _tracker(handler)
    assert t.get_issue(number=7)["title"] == "harness 卡顿"
    (comment,) = t.list_comments(number=7)
    assert comment == {
        "author": "developer",
        "body": "已推进 main v2",
        "created_at": "2026-07-02T09:00:00Z",
    }


def test_get_issue_404_raises() -> None:
    t = _tracker(lambda m, u, j: _Resp(404, text="not found"))
    with pytest.raises(GiteaError) as ei:
        t.get_issue(number=99)
    assert ei.value.status == 404


def test_get_commit_detail_merges_stats_files_diff_and_tags() -> None:
    sha = "a" * 40

    def handler(method: str, url: str, json: Any) -> _Resp:
        if url.endswith(f"/git/commits/{sha}.diff"):
            return _Resp(200, text="diff --git a/agents/main.md b/agents/main.md\n+新增一行")
        if f"/git/commits/{sha}" in url:
            return _Resp(
                200,
                {
                    "sha": sha,
                    "html_url": f"http://gitea/o/r/commit/{sha}",
                    "commit": {
                        "message": "fix: issue #7\n\n详细说明",
                        "author": {"name": "developer", "date": "2026-07-02T08:00:00Z"},
                    },
                    "stats": {"additions": 3, "deletions": 1, "total": 4},
                    "files": [{"filename": "agents/main.md", "status": "modified"}],
                },
            )
        if url.endswith("/tags?limit=50"):
            return _Resp(200, [{"name": "v2", "commit": {"sha": sha}}])
        return _Resp(404, text="no route")

    detail = _tracker(handler).get_commit_detail(sha=sha)
    assert detail["short_sha"] == "a" * 7
    assert detail["message"] == "fix: issue #7\n\n详细说明"  # 全文非首行
    assert detail["tags"] == ["v2"]
    assert detail["stats"] == {"additions": 3, "deletions": 1, "total": 4}
    assert detail["files"] == [{"filename": "agents/main.md", "status": "modified"}]
    assert "+新增一行" in detail["diff"]


def test_get_commit_detail_diff_failure_degrades_to_empty() -> None:
    sha = "b" * 40

    def handler(method: str, url: str, json: Any) -> _Resp:
        if url.endswith(".diff"):
            return _Resp(500, text="boom")
        if f"/git/commits/{sha}" in url:
            return _Resp(200, {"sha": sha, "commit": {"message": "m", "author": {}}})
        if url.endswith("/tags?limit=50"):
            return _Resp(200, [])
        return _Resp(404, text="no route")

    detail = _tracker(handler).get_commit_detail(sha=sha)
    assert detail["diff"] == "" and detail["message"] == "m"  # diff 降级不阻断主体
