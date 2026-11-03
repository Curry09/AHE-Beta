"""GiteaTracker (spec-0002/T2): true backend for the spec-0001/T5 IssueTracker interface.

A thin REST client hitting Gitea /api/v1: translates interface calls into HTTP, keeps state authority in Gitea,
and maintains no client-side state except label ID caching and per-thread HTTP sessions (Spec-0017/T6). Any non-2xx response is converted to GiteaError with status code and endpoint; no errors are silently swallowed.
Configuration (base_url/owner/repo/token) is injected at construction, sourced from spec-0002/T1 backend/deploy/gitea/.env.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Any

import requests
from urllib3.exceptions import HTTPError as TransportHTTPError

from ahe_beta.models import ISSUE_STATES, IssueDraft, IssueRef, OpenIssue
from ahe_beta.observations.transport import make_transport_profile, validate_transport_profile
from ahe_beta.tracker.attachment_transport import (
    MIME_TYPES,
    allows_encoding,
    anonymous_session,
    download_policy,
    validate_r2_location,
)
from ahe_beta.tracker.base import (
    IdempotencyConflictError,
    issue_payload_digest,
    operation_marker,
    operation_marker_digest,
)

# Default color for newly created labels (label semantic set {bug, feature} is preset by T1; this is fallback for missing items only).
_DEFAULT_LABEL_COLOR = "#ededed"

# Spec-0032/T7: PR body closing keywords (closes/fixes/resolves #N) → associated issue numbers (for observation display;
# actual issue closure is performed by Gitea server on merge using the same semantics).
_CLOSING_REF_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)", re.I)


def _parse_closing_refs(*, body: str) -> list[int]:
    """PR body → list of issue numbers referenced by closing keywords (deduplicated, order-preserving)."""
    return list(dict.fromkeys(int(m) for m in _CLOSING_REF_RE.findall(body or "")))


# Hard timeout (seconds) per HTTP request: a hung request without timeout can block the entire feedback loop (main thread poll() waits forever).
_REQUEST_TIMEOUT = 30
_TIMELINE_PAGE_SIZE = 50
_LABEL_PAGE_SIZE = 50


class GiteaError(RuntimeError):
    """Raised when Gitea returns non-2xx or response is unparseable; carries status code and endpoint for locating the call site."""

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
    """Gitea implementation of the IssueTracker protocol. Equivalent to and interchangeable with FakeTracker for run_session."""

    def __init__(self, base_url: str, owner: str, repo: str, token: str) -> None:
        self._api = f"{base_url.rstrip('/')}/api/v1"
        self._owner = owner
        self._repo = repo
        self._token = token
        self._observation_transport: dict | None = None
        # Spec-0017/T6: requests.Session is not thread-safe (cookiejar/internal state mutate concurrently, Gitea will return
        # Set-Cookie), so after parallel segment a each session thread winds down and concurrently create_issue → Session changed to per-thread
        # (thread-local, lazily created, each with full headers). _session_override is a test injection point (see setter).
        self._local = threading.local()
        self._session_override: Any | None = None
        # Label ID cache has no locks: _create_label already has built-in 409/422 race fallback (if created elsewhere, refresh and reuse),
        # and run.py has already warmed up via ensure_labels before the parallel segment starts, so the parallel section is usually read-only.
        self._label_ids: dict[str, int] = {}

    @property
    def _session(self) -> Any:
        """HTTP session for the current thread: override takes precedence (test injection), otherwise per-thread lazy-created independent Session."""
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
        # Test injection point: replace the whole object (all threads read the injected object); single-threaded test semantics equivalent to old field assignment.
        self._session_override = value

    # ---- IssueTracker protocol ----

    def ensure_labels(self, names: list[str]) -> None:
        if not names:
            return  # Empty list is a no-op
        self._refresh_label_cache()
        for name in names:
            if name not in self._label_ids:
                self._create_label(name)

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        missing = [n for n in draft.labels if n not in self._label_ids]
        if missing:
            # Fetch uncached labels first to ensure submission with correct IDs
            self.ensure_labels(missing)
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
            raise ValueError(f"Invalid state: {state!r} (must be one of {ISSUE_STATES})")
        self._request(
            "PATCH",
            f"/repos/{self._owner}/{self._repo}/issues/{number}",
            {"state": state},
        )
        if reason:  # Gitea PATCH does not accept reason field; closure reason is preserved as a comment for traceability
            self.add_comment(number, reason)

    def set_labels(self, number: int, labels: list[str]) -> None:
        """Spec-0025/T3a: bulk replace issue labels. Ensure IDs → PUT /issues/{n}/labels (replacement semantics)."""
        missing = [n for n in labels if n not in self._label_ids]
        if missing:
            self.ensure_labels(missing)
        label_ids = list(dict.fromkeys(self._label_ids[n] for n in labels))
        self._request(
            "PUT",
            f"/repos/{self._owner}/{self._repo}/issues/{number}/labels",
            {"labels": label_ids},
        )

    def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
        """Safe migration proposal body; Gitea 1.22 does not support updating labels in EditIssue."""
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
            raise ValueError(f"Invalid state: {state!r} (must be one of {ISSUE_STATES})")
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

    # ---- Observation read path (not part of IssueTracker protocol, GiteaTracker only) ----

    def list_issues(self, *, state: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        """List issues (including closed + body + timestamps) for complete dashboard display. Read-only observation; no state changes."""
        data = self._request(
            "GET",
            f"/repos/{self._owner}/{self._repo}/issues?state={state}&type=issues&limit={limit}",
            None,
        )
        return [self._issue_dto(item) for item in (data or [])]

    def get_issue(self, *, number: int) -> dict[str, Any]:
        """Fetch a single issue in full (including body/labels/state/timestamp). Raises GiteaError(404) if not found."""
        data = self._request("GET", f"/repos/{self._owner}/{self._repo}/issues/{number}", None)
        return self._issue_dto(data or {})

    def list_comments(self, *, number: int) -> list[dict[str, Any]]:
        """Fetch all comments for an issue (author/content/timestamp) to display the complete discussion in detail panels."""
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
        """Paginate issue timeline and normalize label add/remove direction plus raw fields for debugging.

        In Gitea 1.22, label events use non-empty ``body`` to indicate add and empty body to indicate remove. Unknown events are preserved
        but marked as unknown operation, left to the read-only layer for fail-visible omission, never guessed.
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
                raise GiteaError(0, "list_timeline", "Response is not an array")
            events.extend(self._timeline_event(item) for item in rows if isinstance(item, dict))
            if len(rows) < _TIMELINE_PAGE_SIZE:
                break
            page += 1
        return events

    def get_commit_detail(self, *, sha: str) -> dict[str, Any]:
        """Fetch a single commit in full: complete message + author/timestamp + file-level add/delete stats + raw diff text.

        Diff comes from Gitea's `.diff` raw endpoint (text/plain); file stats from commit API. Tag annotations
        reuse _tags_by_sha (degrades to no tag on failure).
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
        """Raw diff text for a commit; degrades to empty string if unavailable (does not block commit detail body)."""
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
        """Gitea issue response → dashboard DTO (unified shape for read-only observation path)."""
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
        """Gitea timeline item → forge-neutral, JSON-serializable read-only event."""
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
        """List PRs (Spec-0032/T7 delivery-layer observation read path): number/title/three-state/head branch/mergeable/labels.

        Read-only observation; no state changes. Gitea PR state has only open/closed, and merged is a parallel boolean—
        here normalized to three states: open/closed/merged (consistent with delivery-layer semantics). Issue numbers from
        closing keywords in the body are parsed into `closes_issues` for frontend to draw issue-to-PR links.
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
        """List recent commits on harness repo main branch (annotated with vK tags) for dashboard "main branch updates".

        Read-only observation; no state changes. Tag→sha mapping applies vK observation anchors from developer agents back to
        corresponding commits. Tag fetch failure is non-fatal (degrades to no tag); commit body returns normally.
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
        """sha → [tag names]. Tag fetch failure degrades to empty mapping (does not block commit list)."""
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

    # ---- Internal ----

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
        labels, seen_ids = {}, set()
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{self._owner}/{self._repo}/labels?page={page}&limit={_LABEL_PAGE_SIZE}",
                None,
            )
            new_ids = {item["id"] for item in data} - seen_ids
            if not new_ids:
                break
            for item in data:
                # Hosted repositories can contain duplicate label names. Use
                # the first visible ID consistently instead of recreating it.
                labels.setdefault(item["name"], item["id"])
            seen_ids.update(new_ids)
            if len(data) < _LABEL_PAGE_SIZE:
                break
            page += 1
        self._label_ids.update(labels)

    def _create_label(self, name: str) -> None:
        endpoint = f"/repos/{self._owner}/{self._repo}/labels"
        resp = self._session.post(
            self._api + endpoint,
            json={"name": name, "color": _DEFAULT_LABEL_COLOR},
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        # Race condition: already created elsewhere → fall back to GET and retrieve existing id
        if resp.status_code in (409, 422):
            self._refresh_label_cache()
            if name not in self._label_ids:
                raise GiteaError(
                    resp.status_code, endpoint, f"Label {name!r} is still missing after creation"
                )
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
            raise GiteaError(0, "create_issue", f"Response is missing a field: {exc}") from exc
