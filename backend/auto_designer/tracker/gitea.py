"""GiteaTracker（spec-0002/T2）：spec-0001/T5 IssueTracker 接口的真后端。

一个打 Gitea /api/v1 的薄 REST 客户端：把接口调用翻译为 HTTP，状态权威留在 Gitea，
客户端除 label id 缓存与每线程 HTTP 会话（Spec-0017/T6）外无状态。非 2xx 一律转为带
状态码与端点的 GiteaError，不静默返回空回执。
配置（base_url/owner/repo/token）由构造注入，来源是 spec-0002/T1 的 backend/deploy/gitea/.env。
"""

from __future__ import annotations

import re
import threading
from typing import Any

import requests

from auto_designer.models import ISSUE_STATES, IssueDraft, IssueRef, OpenIssue

# 新建 label 的默认颜色（标签语义集 {bug,feature} 由 T1 预置；此处仅兜底建缺失项）。
_DEFAULT_LABEL_COLOR = "#ededed"

# Spec-0032/T7：PR 正文 closing 关键字（closes/fixes/resolves #N）→ 关联 issue 号（观测展示用；
# 真正的关票由 Gitea 服务端在合并时按同一语义执行）。
_CLOSING_REF_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)", re.I)


def _parse_closing_refs(*, body: str) -> list[int]:
    """PR 正文 → closing 关键字引用的 issue 号列表（去重保序）。"""
    return list(dict.fromkeys(int(m) for m in _CLOSING_REF_RE.findall(body or "")))


# 每次 HTTP 请求的硬超时（秒）：无超时的请求一旦挂死会把整条闭环卡住（主线程 poll() 永等）。
_REQUEST_TIMEOUT = 30


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
        self._token = token
        # Spec-0017/T6：requests.Session 非线程安全（cookiejar/内部状态并发变异，Gitea 会回
        # Set-Cookie），a 段并行后各会话线程收尾并发 create_issue → Session 改每线程一个
        # （thread-local，惰性新建、各带全 header）。_session_override 是测试注入口（见 setter）。
        self._local = threading.local()
        self._session_override: Any | None = None
        # label id 缓存不加锁：_create_label 已内置 409/422 竞态回退（他处已建则 refresh 复用），
        # 且 run.py 开跑前已 ensure_labels 预热，并行段内通常纯读。
        self._label_ids: dict[str, int] = {}

    @property
    def _session(self) -> Any:
        """当前线程的 HTTP 会话：override 优先（测试注入），否则每线程惰性建独立 Session。"""
        if self._session_override is not None:
            return self._session_override
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(
                {"Authorization": f"token {self._token}", "Content-Type": "application/json"}
            )
            self._local.session = session
        return session

    @_session.setter
    def _session(self, value: Any) -> None:
        # 测试注入口：整体替换（所有线程都读到注入对象）；单线程测试语义与旧字段赋值等价。
        self._session_override = value

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

    def set_labels(self, number: int, labels: list[str]) -> None:
        """Spec-0025/T3a：整组替换 issue 标签。ensure 拿 id → PUT /issues/{n}/labels（替换语义）。"""
        missing = [n for n in labels if n not in self._label_ids]
        if missing:
            self.ensure_labels(missing)
        label_ids = [self._label_ids[n] for n in labels]
        self._request(
            "PUT",
            f"/repos/{self._owner}/{self._repo}/issues/{number}/labels",
            {"labels": label_ids},
        )

    # ---- 观测读路径（非 IssueTracker 协议，仅 GiteaTracker 提供）----

    def list_issues(self, *, state: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        """列 issue（含已关闭 + 正文 + 时间戳），供观测看板完整展示。纯观测、不改任何状态。"""
        data = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/issues?state={state}&type=issues&limit={limit}",
            None,
        )
        return [self._issue_dto(item) for item in (data or [])]

    def get_issue(self, *, number: int) -> dict[str, Any]:
        """取单条 issue 全量（含正文/labels/状态/时间戳）。不存在时抛 GiteaError(404)。"""
        data = self._request("GET", f"/repos/{self._owner}/{self._repo}/issues/{number}", None)
        return self._issue_dto(data or {})

    def list_comments(self, *, number: int) -> list[dict[str, Any]]:
        """取某 issue 的全部评论（作者/内容/时间），供详情面板展示完整讨论过程。"""
        data = self._request(
            "GET", f"/repos/{self._owner}/{self._repo}/issues/{number}/comments", None
        )
        return [
            {
                "author": (item.get("user") or {}).get("login") or "",
                "body": item.get("body") or "",
                "created_at": item.get("created_at") or "",
            }
            for item in (data or [])
        ]

    def get_commit_detail(self, *, sha: str) -> dict[str, Any]:
        """取单个 commit 全量：message 全文 + 作者/时间 + 文件级增删统计 + 原始 diff 文本。

        diff 走 Gitea 的 `.diff` 原文端点（text/plain）；文件统计走 commit API。tag 标注
        沿用 _tags_by_sha（失败降级为无 tag）。
        """
        item = (
            self._request(
                "GET", f"/repos/{self._owner}/{self._repo}/git/commits/{sha}?stat=true", None
            )
            or {}
        )
        commit = item.get("commit") or {}
        author = commit.get("author") or {}
        stats = item.get("stats") or {}
        return {
            "sha": item.get("sha") or sha,
            "short_sha": (item.get("sha") or sha)[:7],
            "message": (commit.get("message") or "").strip(),
            "author": author.get("name") or "",
            "date": author.get("date") or "",
            "url": item.get("html_url") or "",
            "tags": self._tags_by_sha().get(item.get("sha") or sha, []),
            "stats": {
                "additions": stats.get("additions") or 0,
                "deletions": stats.get("deletions") or 0,
                "total": stats.get("total") or 0,
            },
            "files": [
                {"filename": f.get("filename") or "", "status": f.get("status") or ""}
                for f in (item.get("files") or [])
            ],
            "diff": self._commit_diff(sha=sha),
        }

    def _commit_diff(self, *, sha: str) -> str:
        """commit 原始 diff 文本；取不到降级为空串（不阻断 commit 详情主体）。"""
        endpoint = f"/repos/{self._owner}/{self._repo}/git/commits/{sha}.diff"
        try:
            resp = self._session.request("GET", self._api + endpoint, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException:
            return ""
        if not 200 <= resp.status_code < 300:
            return ""
        return resp.text or ""

    @staticmethod
    def _issue_dto(item: dict[str, Any]) -> dict[str, Any]:
        """Gitea issue 响应 → 看板 DTO（观测读路径统一形状）。"""
        return {
            "number": item.get("number") or 0,
            "title": item.get("title") or "",
            "body": item.get("body") or "",
            "labels": [lbl.get("name") or "" for lbl in (item.get("labels") or [])],
            "state": item.get("state") or "open",
            "created_at": item.get("created_at") or "",
            "closed_at": item.get("closed_at") or None,
            "url": item.get("html_url") or "",
        }

    def list_pulls(self, *, state: str = "open", limit: int = 20) -> list[dict[str, Any]]:
        """列 PR（Spec-0032/T7 交付面观测读路径）：号/标题/三态 state/head 分支/mergeable/labels。

        纯观测、不改任何状态。Gitea 的 PR state 只有 open/closed、merged 是并列布尔——此处归一为
        open/closed/merged 三态（与交付面语义一致）。closing 关键字关联的 issue 号从正文解析出
        `closes_issues` 供前端画「票 → PR」链。
        """
        data = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/pulls"
            f"?state={state}&sort=recentupdate&limit={limit}",
            None,
        )
        out: list[dict[str, Any]] = []
        for item in data or []:
            merged = item.get("merged") is True
            out.append(
                {
                    "number": item.get("number") or 0,
                    "title": item.get("title") or "",
                    "state": "merged" if merged else (item.get("state") or "open"),
                    "head_branch": ((item.get("head") or {}).get("ref")) or "",
                    "mergeable": item.get("mergeable"),
                    "labels": [lbl.get("name") or "" for lbl in (item.get("labels") or [])],
                    "closes_issues": _parse_closing_refs(body=str(item.get("body") or "")),
                    "url": item.get("html_url") or "",
                    "created_at": item.get("created_at") or "",
                    "updated_at": item.get("updated_at") or "",
                }
            )
        return out

    def list_recent_commits(self, *, limit: int = 15) -> list[dict[str, Any]]:
        """列 harness 仓 main 最近 commit（带 vK tag 标注），供观测看板「main 分支更新」。

        纯观测、不改任何状态。tag→sha 映射把开发者 agent 打的 vK 观测锚点贴回对应 commit。
        取标签失败不致命（降级为无 tag），commit 主体照常返回。
        """
        commits = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/commits?limit={limit}&stat=false",
            None,
        )
        tags_by_sha = self._tags_by_sha()
        out: list[dict[str, Any]] = []
        for item in commits or []:
            sha = item.get("sha") or ""
            commit = item.get("commit") or {}
            author = commit.get("author") or {}
            message = (commit.get("message") or "").strip()
            out.append(
                {
                    "sha": sha,
                    "short_sha": sha[:7],
                    "message": message.splitlines()[0] if message else "",
                    "author": author.get("name") or "",
                    "date": author.get("date") or "",
                    "url": item.get("html_url") or "",
                    "tags": tags_by_sha.get(sha, []),
                }
            )
        return out

    def _tags_by_sha(self) -> dict[str, list[str]]:
        """sha → [tag 名]。取标签失败降级为空映射（不阻断 commit 列表）。"""
        try:
            tags = self._request("GET", f"/repos/{self._owner}/{self._repo}/tags?limit=50", None)
        except GiteaError:
            return {}
        mapping: dict[str, list[str]] = {}
        for tag in tags or []:
            sha = (tag.get("commit") or {}).get("sha") or ""
            name = tag.get("name") or ""
            if sha and name:
                mapping.setdefault(sha, []).append(name)
        return mapping

    # ---- 内部 ----

    def _refresh_label_cache(self) -> None:
        data = self._request("GET", f"/repos/{self._owner}/{self._repo}/labels", None)
        for item in data:
            self._label_ids[item["name"]] = item["id"]

    def _create_label(self, name: str) -> None:
        endpoint = f"/repos/{self._owner}/{self._repo}/labels"
        resp = self._session.post(
            self._api + endpoint,
            json={"name": name, "color": _DEFAULT_LABEL_COLOR},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code in (409, 422):  # 竞态：他处已建 → 回退 GET 取既有 id
            self._refresh_label_cache()
            if name not in self._label_ids:
                raise GiteaError(resp.status_code, endpoint, f"label {name!r} 建后仍缺")
            return
        data = self._ok(resp, endpoint)
        self._label_ids[name] = data["id"]

    def _request(self, method: str, endpoint: str, json_body: dict[str, Any] | None) -> Any:
        resp = self._session.request(
            method, self._api + endpoint, json=json_body, timeout=_REQUEST_TIMEOUT
        )
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
