"""GiteaTracker（spec-0002/T2）：spec-0001/T5 IssueTracker 接口的真后端。

一个打 Gitea /api/v1 的薄 REST 客户端：把接口调用翻译为 HTTP，状态权威留在 Gitea，
客户端除 label id 缓存外无状态。非 2xx 一律转为带状态码与端点的 GiteaError，不静默返回空回执。
配置（base_url/owner/repo/token）由构造注入，来源是 spec-0002/T1 的 infra/gitea/.env。
"""

from __future__ import annotations

from typing import Any

import requests

from auto_designer.models import ISSUE_STATES, IssueDraft, IssueRef, OpenIssue

# 新建 label 的默认颜色（标签语义集 {bug,feature} 由 T1 预置；此处仅兜底建缺失项）。
_DEFAULT_LABEL_COLOR = "#ededed"


class GiteaError(RuntimeError):
    """Gitea 返回非 2xx 或响应不可解析时抛出，携带状态码与端点便于在调用点定位。"""

    def __init__(self, status: int, endpoint: str, detail: str = "") -> None:
        super().__init__(f"Gitea {status} @ {endpoint}{f': {detail}' if detail else ''}")
        self.status = status
        self.endpoint = endpoint


class GiteaTracker:
    """IssueTracker 协议的 Gitea 实现。与 FakeTracker 对 run_session 等价、可互换。"""

    def __init__(self, base_url: str, owner: str, repo: str, token: str) -> None:
        self._api = f"{base_url.rstrip('/')}/api/v1"
        self._owner = owner
        self._repo = repo
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"token {token}", "Content-Type": "application/json"}
        )
        self._label_ids: dict[str, int] = {}

    # ---- IssueTracker 协议 ----

    def ensure_labels(self, names: list[str]) -> None:
        if not names:
            return  # 空列表 no-op
        self._refresh_label_cache()
        for name in names:
            if name not in self._label_ids:
                self._create_label(name)

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        missing = [n for n in draft.labels if n not in self._label_ids]
        if missing:
            self.ensure_labels(missing)  # 未缓存的 label 先补齐，保证一次带正确 id 提交
        label_ids = [self._label_ids[n] for n in draft.labels]
        data = self._request(
            "POST",
            f"/repos/{self._owner}/{self._repo}/issues",
            {"title": draft.title, "body": draft.body, "labels": label_ids},
        )
        return self._parse_issue_ref(data)

    def list_open_issues(self) -> list[OpenIssue]:
        data = self._request(
            "GET", f"/repos/{self._owner}/{self._repo}/issues?state=open&type=issues", None
        )
        return [
            OpenIssue(
                number=item["number"],
                title=item.get("title", ""),
                body=item.get("body") or "",
                labels=[lbl["name"] for lbl in item.get("labels", [])],
                state=item.get("state", "open"),
            )
            for item in (data or [])
        ]

    def add_comment(self, number: int, body: str) -> None:
        self._request(
            "POST",
            f"/repos/{self._owner}/{self._repo}/issues/{number}/comments",
            {"body": body},
        )

    def set_state(self, number: int, state: str, reason: str) -> None:
        if state not in ISSUE_STATES:
            raise ValueError(f"非法 state：{state!r}（须属 {ISSUE_STATES}）")
        self._request(
            "PATCH",
            f"/repos/{self._owner}/{self._repo}/issues/{number}",
            {"state": state},
        )
        if reason:  # Gitea PATCH 不收 reason 字段，关闭理由以 comment 保留可追溯
            self.add_comment(number, reason)

    # ---- 内部 ----

    def _refresh_label_cache(self) -> None:
        data = self._request("GET", f"/repos/{self._owner}/{self._repo}/labels", None)
        for item in data:
            self._label_ids[item["name"]] = item["id"]

    def _create_label(self, name: str) -> None:
        endpoint = f"/repos/{self._owner}/{self._repo}/labels"
        resp = self._session.post(
            self._api + endpoint, json={"name": name, "color": _DEFAULT_LABEL_COLOR}
        )
        if resp.status_code in (409, 422):  # 竞态：他处已建 → 回退 GET 取既有 id
            self._refresh_label_cache()
            if name not in self._label_ids:
                raise GiteaError(resp.status_code, endpoint, f"label {name!r} 建后仍缺")
            return
        data = self._ok(resp, endpoint)
        self._label_ids[name] = data["id"]

    def _request(self, method: str, endpoint: str, json_body: dict[str, Any] | None) -> Any:
        resp = self._session.request(method, self._api + endpoint, json=json_body)
        return self._ok(resp, endpoint)

    def _ok(self, resp: requests.Response, endpoint: str) -> Any:
        if not 200 <= resp.status_code < 300:
            raise GiteaError(resp.status_code, endpoint, resp.text[:200])
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def _parse_issue_ref(self, data: Any) -> IssueRef:
        try:
            return IssueRef(number=data["number"], url=data["html_url"], state=data["state"])
        except (KeyError, TypeError) as exc:
            raise GiteaError(0, "create_issue", f"响应缺字段：{exc}") from exc
