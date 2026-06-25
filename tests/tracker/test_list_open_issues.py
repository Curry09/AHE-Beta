"""spec-0003：IssueTracker.list_open_issues 读路径单测（Fake + Gitea）。"""

from __future__ import annotations

from test_gitea import _FakeSession, _Resp

from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.tracker.gitea import GiteaTracker


def test_fake_lists_only_open() -> None:
    t = FakeTracker()
    r1 = t.create_issue(IssueDraft(title="a", body="ba", labels=["bug"]))
    t.create_issue(IssueDraft(title="b", body="bb"))
    t.set_state(r1.number, "closed", "done")  # 关掉第一条
    issues = t.list_open_issues()
    assert [i.number for i in issues] == [2]
    assert issues[0].title == "b" and issues[0].state == "open"


def test_fake_empty() -> None:
    assert FakeTracker().list_open_issues() == []


def test_gitea_parses_open_issues() -> None:
    def handler(method, url, json):
        return _Resp(
            200,
            [
                {
                    "number": 3,
                    "title": "t3",
                    "body": "b3",
                    "state": "open",
                    "labels": [{"name": "bug"}],
                },
                {"number": 5, "title": "t5", "body": None, "state": "open", "labels": []},
            ],
        )

    t = GiteaTracker(base_url="http://gitea", owner="o", repo="r", token="T")
    t._session = _FakeSession(handler)
    issues = t.list_open_issues()
    assert [(i.number, i.labels) for i in issues] == [(3, ["bug"]), (5, [])]
    assert issues[1].body == ""  # body=None → ""
