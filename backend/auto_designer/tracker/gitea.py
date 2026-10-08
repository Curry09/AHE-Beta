"""GiteaTracker（spec-0002/T2）：spec-0001/T5 IssueTracker 接口的真后端。

一个打 Gitea /api/v1 的薄 REST 客户端：把接口调用翻译为 HTTP，状态权威留在 Gitea，
客户端除 label id 缓存与每线程 HTTP 会话（Spec-0017/T6）外无状态。非 2xx 一律转为带
状态码与端点的 GiteaError，不静默返回空回执。
配置（base_url/owner/repo/token）由构造注入，来源是 spec-0002/T1 的 backend/deploy/gitea/.env。
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Any

import requests
from urllib3.exceptions import HTTPError as TransportHTTPError

from auto_designer.models import ISSUE_STATES, IssueDraft, IssueRef, OpenIssue
from auto_designer.observations.transport import make_transport_profile, validate_transport_profile
from auto_designer.tracker.attachment_transport import (
    MIME_TYPES,
    allows_encoding,
    anonymous_session,
    download_policy,
    validate_r2_location,
)
from auto_designer.tracker.base import (
    IdempotencyConflictError,
    issue_payload_digest,
    operation_marker,
    operation_marker_digest,
)

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
_TIMELINE_PAGE_SIZE = 50


class GiteaError(RuntimeError):
    """Gitea 返回非 2xx 或响应不可解析时抛出，携带状态码与端点便于在调用点定位。"""

    def __init__(self, status: int, endpoint: str, detail: str = "") -> None:
        super().__init__(f"Gitea {status} @ {endpoint}{f': {detail}' if detail else ''}")
        self.status = status
        self.endpoint = endpoint


class IssueMigrationError(RuntimeError):
    """A semantic issue migration did not reach its requested post-state."""

    def __init__(
        self,
        *,
        number: int,
        operation: str,
        primary: BaseException | str,
        rollback: BaseException | str | None,
        observed: dict[str, Any] | None,
    ) -> None:
        detail = f"issue #{number} {operation} failed: {primary}"
        if rollback is not None:
            detail += f"; rollback: {rollback}"
        super().__init__(detail)
        self.number = number
        self.operation = operation
        self.primary = primary
        self.rollback = rollback
        self.observed = observed


class GiteaTracker:
    """IssueTracker 协议的 Gitea 实现。与 FakeTracker 对 run_session 等价、可互换。"""

    def __init__(self, base_url: str, owner: str, repo: str, token: str) -> None:
        self._api = f"{base_url.rstrip('/')}/api/v1"
        self._owner = owner
        self._repo = repo
        self._token = token
        self._observation_transport: dict | None = None
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

    def create_issue_once(self, draft: IssueDraft, *, operation_key: str) -> IssueRef:
        """Spec-0064/T1: reconcile a marked issue before retrying its creation."""
        payload_digest = issue_payload_digest(draft)
        existing = self._find_issue_operation(operation_key=operation_key)
        if existing is not None:
            number, observed_digest, url, state = existing
            if observed_digest != payload_digest:
                raise IdempotencyConflictError(
                    f"operation key already created issue #{number} with another payload"
                )
            return IssueRef(number=number, url=url, state=state)
        marker = operation_marker(operation_key=operation_key, payload_digest=payload_digest)
        body = f"{draft.body.rstrip()}\n\n{marker}" if draft.body else marker
        return self.create_issue(
            IssueDraft(title=draft.title, body=body, labels=list(draft.labels))
        )

    def list_open_issues(self) -> list[OpenIssue]:
        data = []
        page = 1
        while True:
            items = (
                self._request(
                    "GET",
                    f"/repos/{self._owner}/{self._repo}/issues?state=open&type=issues&limit=50&page={page}",
                    None,
                )
                or []
            )
            data.extend(items)
            if len(items) < 50:
                break
            page += 1
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

    def add_comment_once(self, number: int, body: str, *, operation_key: str) -> None:
        """Spec-0064/T1: reconcile a marked comment before retrying its creation."""
        payload_digest = hashlib.sha256(body.encode()).hexdigest()
        for comment in self.list_comments(number=number):
            existing = operation_marker_digest(
                text=str(comment.get("body") or ""), operation_key=operation_key
            )
            if existing is None:
                continue
            if existing != payload_digest:
                raise IdempotencyConflictError(
                    f"operation key already added another comment to issue #{number}"
                )
            return
        marker = operation_marker(operation_key=operation_key, payload_digest=payload_digest)
        self.add_comment(number, f"{body.rstrip()}\n\n{marker}" if body else marker)

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

    def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
        """安全迁移提案主体；Gitea 1.22 不支持在 EditIssue 中更新 labels。"""
        before = self.get_issue(number=number)
        self._request(
            "PATCH",
            f"/repos/{self._owner}/{self._repo}/issues/{number}",
            {"title": title, "body": body},
        )
        try:
            self.set_labels(number, labels)
            observed = self.get_issue(number=number)
            if not self._matches(observed, title=title, body=body, labels=labels, state=None):
                raise ValueError("postcondition mismatch")
        except Exception as exc:
            rollback_error: BaseException | None = None
            try:
                current = self.get_issue(number=number)
                if current.get("title") != title or current.get("body") != body:
                    raise RuntimeError(
                        "rollback skipped because issue content changed concurrently"
                    )
                self._request(
                    "PATCH",
                    f"/repos/{self._owner}/{self._repo}/issues/{number}",
                    {"title": before["title"], "body": before["body"]},
                )
            except Exception as rollback_exc:
                rollback_error = rollback_exc
            raise IssueMigrationError(
                number=number,
                operation="update_issue",
                primary=exc,
                rollback=rollback_error,
                observed=self._observed_issue(number=number),
            ) from exc

    def transition_issue(self, number: int, *, state: str, labels: list[str]) -> None:
        if state not in ISSUE_STATES:
            raise ValueError(f"非法 state：{state!r}（须属 {ISSUE_STATES}）")
        before = self.get_issue(number=number)
        self.set_labels(number, labels)
        try:
            self._request(
                "PATCH",
                f"/repos/{self._owner}/{self._repo}/issues/{number}",
                {"state": state},
            )
            observed = self.get_issue(number=number)
            if not self._matches(observed, title=None, body=None, labels=labels, state=state):
                raise ValueError("postcondition mismatch")
        except Exception as exc:
            rollback_error: BaseException | None = None
            try:
                current = self.get_issue(number=number)
                if set(current.get("labels") or []) != set(labels):
                    raise RuntimeError("rollback skipped because issue labels changed concurrently")
                self.set_labels(number, list(before["labels"]))
            except Exception as rollback_exc:
                rollback_error = rollback_exc
            raise IssueMigrationError(
                number=number,
                operation="transition_issue",
                primary=exc,
                rollback=rollback_error,
                observed=self._observed_issue(number=number),
            ) from exc

    @staticmethod
    def _matches(
        observed: dict[str, Any],
        *,
        title: str | None,
        body: str | None,
        labels: list[str],
        state: str | None,
    ) -> bool:
        return (
            (title is None or observed.get("title") == title)
            and (body is None or observed.get("body") == body)
            and set(observed.get("labels") or []) == set(labels)
            and (state is None or observed.get("state") == state)
        )

    def _observed_issue(self, *, number: int) -> dict[str, Any] | None:
        try:
            return self.get_issue(number=number)
        except Exception:  # noqa: BLE001 - error object remains useful when observation also fails
            return None

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

    def _find_issue_operation(self, *, operation_key: str) -> tuple[int, str, str, str] | None:
        page = 1
        while True:
            rows = (
                self._request(
                    "GET",
                    f"/repos/{self._owner}/{self._repo}/issues"
                    f"?state=all&type=issues&limit=50&page={page}",
                    None,
                )
                or []
            )
            for item in rows:
                observed = operation_marker_digest(
                    text=str(item.get("body") or ""), operation_key=operation_key
                )
                if observed is not None:
                    return (
                        int(item["number"]),
                        observed,
                        str(item.get("html_url") or ""),
                        str(item.get("state") or "open"),
                    )
            if len(rows) < 50:
                return None
            page += 1

    def list_timeline(self, *, number: int) -> list[dict[str, Any]]:
        """分页读取 issue timeline，并归一 label add/remove 方向及调试所需原始字段。

        Gitea 1.22 的 label event 用非空 ``body`` 表示 add、空 body 表示 remove。未知事件保留，
        但 operation 标成 unknown，交给纯观测层 fail-visible 地忽略，绝不猜测方向。
        """
        events: list[dict[str, Any]] = []
        page = 1
        while True:
            rows = self._request(
                "GET",
                f"/repos/{self._owner}/{self._repo}/issues/{number}/timeline"
                f"?page={page}&limit={_TIMELINE_PAGE_SIZE}",
                None,
            )
            if not isinstance(rows, list):
                raise GiteaError(0, "list_timeline", "响应不是数组")
            events.extend(self._timeline_event(item) for item in rows if isinstance(item, dict))
            if len(rows) < _TIMELINE_PAGE_SIZE:
                break
            page += 1
        return events

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
            resp = self._session.request(
                "GET", self._api + endpoint, timeout=_REQUEST_TIMEOUT, allow_redirects=False
            )
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

    @staticmethod
    def _timeline_event(item: dict[str, Any]) -> dict[str, Any]:
        """Gitea timeline item → forge-neutral、JSON 可序列化的只读事件。"""
        event_type = str(item.get("type") or "")
        body = item.get("body")
        operation = "unknown"
        if event_type == "label":
            operation = "add" if body not in (None, "") else "remove"
        label = item.get("label") or {}
        actor = item.get("user") or item.get("actor") or {}
        return {
            "id": item.get("id"),
            "created_at": item.get("created_at") or "",
            "actor": actor.get("login") or "",
            "type": event_type,
            "label": label.get("name") or "",
            "operation": operation,
            "body": "" if body is None else str(body),
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

    def find_observation_gap(self, *, marker: str) -> int | None:
        # Paginate including closed issues: closing a ticket must not break retry identity.
        for page in range(1, 101):
            rows = self._request(
                "GET",
                f"/repos/{self._owner}/{self._repo}/issues"
                f"?state=all&type=issues&limit=50&page={page}",
                None,
            )
            for item in rows:
                if marker in (item.get("body") or ""):
                    return int(item["number"])
            if len(rows) < 50:
                return None
        raise ValueError("gap identity scan exhausted; refusing ambiguous duplicate creation")

    def authenticated_login(self) -> str:
        return str(self._request("GET", "/user", None)["login"])

    def preflight_observations(self) -> dict:
        selected = self.select_observation_transport()
        profile = self.observation_transport or make_transport_profile(
            repository=selected["repository"]
        )
        settings = self._attachment_settings
        if not allows_encoding(settings.get("allowed_types"), profile["encoding"]):
            raise ValueError(
                "frozen observation encoding no longer supported; use a new experiment identity"
            )
        if profile["download_policy"] != selected["download_policy"]:
            raise ValueError("observation download policy changed; use a new experiment identity")
        return {
            "repository": selected["repository"],
            "format": "artifact-observations-v1",
            "max_transfer_bytes": 4_000_000,
        }

    @property
    def observation_transport(self) -> dict | None:
        return dict(self._observation_transport) if self._observation_transport else None

    def bind_observation_transport(self, profile: dict, *, reader_verified: bool = False) -> None:
        profile = validate_transport_profile(
            profile, repository=f"{self._api}/repos/{self._owner}/{self._repo}"
        )
        if (
            profile["download_policy"] == "gitea-com-r2-v1"
            and download_policy(self._api.removesuffix("/api/v1")) != "gitea-com-r2-v1"
        ):
            raise ValueError("hosted attachment policy requires https://gitea.com")
        if (
            profile["encoding"] != "gzip" or profile["download_policy"] != "same-origin-v1"
        ) and not reader_verified:
            raise ValueError("new observation transport requires verified reader capability")
        if self._observation_transport is not None and self._observation_transport != profile:
            raise ValueError("observation transport is already bound")
        self._observation_transport = profile

    def select_observation_transport(self) -> dict:
        settings = self._request("GET", "/settings/attachment", None)
        repo = self._request("GET", f"/repos/{self._owner}/{self._repo}", None)
        if (
            not settings.get("enabled")
            or int(settings.get("max_size", 0)) < 4
            or not (
                repo.get("permissions", {}).get("push") or repo.get("permissions", {}).get("admin")
            )
        ):
            raise ValueError("observation attachment transport preflight failed")
        encoding = next(
            (
                item
                for item in ("gzip", "zip")
                if allows_encoding(settings.get("allowed_types"), item)
            ),
            None,
        )
        if encoding is None:
            raise ValueError("Gitea attachment rules allow neither gzip nor ZIP evidence")
        self._attachment_settings = settings
        return make_transport_profile(
            repository=f"{self._api}/repos/{self._owner}/{self._repo}",
            encoding=encoding,
            download_policy=download_policy(self._api.removesuffix("/api/v1")),
        )

    def list_issue_assets(self, *, number: int) -> list[dict]:
        import json

        data = self._observation_bytes(
            url=f"{self._api}/repos/{self._owner}/{self._repo}/issues/{number}/assets",
            limit=1_000_000,
        )
        return json.loads(data)

    def upload_issue_asset(self, *, number: int, name: str, data: bytes) -> dict:
        endpoint = f"/repos/{self._owner}/{self._repo}/issues/{number}/assets"
        response = self._session.post(
            self._api + endpoint,
            files={
                "attachment": (
                    name,
                    data,
                    MIME_TYPES[(self.observation_transport or {}).get("encoding", "gzip")],
                )
            },
            headers={"Content-Type": None},
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        return self._ok(response, endpoint)

    def download_issue_asset(self, *, number: int, asset_id: int, limit: int) -> bytes:
        assets = self.list_issue_assets(number=number)
        asset = next((a for a in assets if a["id"] == asset_id), None)
        if asset is None or not re.fullmatch(r"[a-fA-F0-9-]{36}", str(asset.get("uuid", ""))):
            raise ValueError("attachment is not a member of this issue")
        # Never follow browser_download_url supplied by the server or model across origins.
        url = self._api.removesuffix("/api/v1") + "/attachments/" + asset["uuid"]
        return self._observation_bytes(url=url, limit=limit, attachment=True)

    def _observation_bytes(self, *, url: str, limit: int, attachment: bool = False) -> bytes:
        deadline = time.monotonic() + 15
        with self._session.get(
            url,
            stream=True,
            timeout=(5, 5),
            allow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            if (
                attachment
                and response.status_code in (302, 303, 307, 308)
                and (self.observation_transport or {}).get("download_policy") == "gitea-com-r2-v1"
            ):
                location = validate_r2_location(response.headers.get("Location", ""))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("attachment download exceeds budget")
                try:
                    with anonymous_session(self._session, location) as session:
                        with session.get(
                            location,
                            stream=True,
                            timeout=(min(5, remaining), min(5, remaining)),
                            allow_redirects=False,
                            headers={"Accept-Encoding": "identity"},
                        ) as external:
                            return self._read_observation_response(
                                external, limit=limit, deadline=deadline
                            )
                except (requests.RequestException, TransportHTTPError, OSError):
                    raise ValueError("signed observation attachment download failed") from None
            return self._read_observation_response(response, limit=limit, deadline=deadline)

    def _read_observation_response(self, response, *, limit: int, deadline: float) -> bytes:
        if response.status_code != 200:
            raise GiteaError(response.status_code, "attachment download")
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("attachment download exceeds budget")
            # requests leaves the streaming socket at its initial read timeout.
            # Tighten it to the remaining shared budget before each read1.
            raw_socket = getattr(
                getattr(getattr(getattr(response.raw, "_fp", None), "fp", None), "raw", None),
                "_sock",
                None,
            )
            if raw_socket is not None:
                raw_socket.settimeout(min(5, remaining))
            # read1 returns available data; read(n) can wait forever on a drip-fed body.
            chunk = response.raw.read1(min(65536, limit + 1 - size), decode_content=False)
            size += len(chunk)
            if size > limit or time.monotonic() > deadline:
                raise ValueError("attachment download exceeds budget")
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

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
            allow_redirects=False,
        )
        if resp.status_code in (409, 422):  # 竞态：他处已建 → 回退 GET 取既有 id
            self._refresh_label_cache()
            if name not in self._label_ids:
                raise GiteaError(resp.status_code, endpoint, f"label {name!r} 建后仍缺")
            return
        data = self._ok(resp, endpoint)
        self._label_ids[name] = data["id"]

    def _request(self, method: str, endpoint: str, json_body: dict[str, Any] | None) -> Any:
        # Gitea can briefly reset a read connection while its git backend is
        # servicing a newly-created repository.  GET is safe to retry; do not
        # blindly retry POST/PATCH because a server-side write may already
        # have succeeded.
        attempts = 4 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                resp = self._session.request(
                    method,
                    self._api + endpoint,
                    json=json_body,
                    timeout=_REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
                if (
                    method.upper() == "GET"
                    and resp.status_code in {408, 429, 500, 502, 503, 504}
                    and attempt + 1 < attempts
                ):
                    time.sleep(2**attempt)
                    continue
                return self._ok(resp, endpoint)
            except requests.RequestException:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(2**attempt)

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
