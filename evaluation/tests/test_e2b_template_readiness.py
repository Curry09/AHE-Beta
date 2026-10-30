"""A cached alias is reusable only when its selected build is ready."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from e2b.exceptions import TemplateException
from e2b.template.types import TemplateBuildStatus
from harbor.environments.e2b import E2BEnvironment

from evaluation.environments import e2b
from evaluation.environments.base import TaskEnvironmentMixin


@pytest.fixture
def cache(monkeypatch):
    close = AsyncMock()
    client = SimpleNamespace(get_async_httpx_client=lambda: SimpleNamespace(aclose=close))
    monkeypatch.setattr(e2b, "get_api_client", lambda config: client)
    lookup = AsyncMock(
        return_value=SimpleNamespace(status_code=200, parsed=SimpleNamespace(template_id="real-id"))
    )
    monkeypatch.setattr(e2b.get_templates_aliases_alias, "asyncio_detailed", lookup)
    tags = AsyncMock(return_value=[SimpleNamespace(tag="default", build_id="selected-build")])
    monkeypatch.setattr(e2b.AsyncTemplate, "get_tags", tags)
    status = AsyncMock(return_value=SimpleNamespace(status=TemplateBuildStatus.READY, reason=None))
    monkeypatch.setattr(e2b.AsyncTemplate, "get_build_status", status)
    env = e2b.HarnessE2BEnvironment.__new__(e2b.HarnessE2BEnvironment)
    env._template_name = "cached-alias"
    env._force_template_rebuild = False
    return SimpleNamespace(env=env, lookup=lookup, tags=tags, status=status, close=close)


def test_default_build_identity_and_ready_cache(cache):
    cache.tags.return_value.append(SimpleNamespace(tag="new-experiment", build_id="other-build"))
    assert asyncio.run(cache.env._does_template_exist())
    build = cache.status.await_args.args[0]
    assert (build.template_id, build.build_id) == ("real-id", "selected-build")
    assert cache.status.await_args.kwargs == {"request_timeout": 30}
    cache.close.assert_awaited_once()


def test_missing_alias_allows_normal_build(cache):
    cache.lookup.return_value.status_code = 404
    assert not asyncio.run(cache.env._does_template_exist())
    cache.tags.assert_not_awaited()
    cache.status.assert_not_awaited()
    cache.close.assert_awaited_once()


def test_alias_access_error_is_not_a_cache_miss(cache, monkeypatch):
    cache.lookup.return_value.status_code = 403
    monkeypatch.setattr(e2b, "handle_api_exception", lambda response, cls: cls("access denied"))
    with pytest.raises(TemplateException, match="access denied"):
        asyncio.run(cache.env._does_template_exist())
    cache.tags.assert_not_awaited()
    cache.close.assert_awaited_once()


def test_missing_default_tag_is_not_a_ready_cache(cache):
    cache.tags.return_value = [SimpleNamespace(tag="other", build_id="other-build")]
    with pytest.raises(TemplateException, match="has no default tag"):
        asyncio.run(cache.env._does_template_exist())
    cache.status.assert_not_awaited()


def test_failed_build_retains_provider_reason(cache):
    cache.status.return_value = SimpleNamespace(
        status=TemplateBuildStatus.ERROR,
        reason=SimpleNamespace(message="Debian provisioning package 404"),
    )
    with pytest.raises(TemplateException, match="selected-build is error: Debian provisioning"):
        asyncio.run(cache.env._does_template_exist())
    cache.status.assert_awaited_once()


def test_native_start_never_launches_a_sandbox_from_failed_cache(cache, monkeypatch):
    cache.status.return_value = SimpleNamespace(
        status=TemplateBuildStatus.ERROR, reason=SimpleNamespace(message="image exceeds disk limit")
    )
    build = AsyncMock()
    monkeypatch.setattr(E2BEnvironment, "_create_template", build)
    cache.env._create_sandbox = AsyncMock()
    cache.env.stop = AsyncMock()
    with pytest.raises(TemplateException, match="image exceeds disk limit"):
        asyncio.run(cache.env.start(False))
    build.assert_not_awaited()
    cache.env._create_sandbox.assert_not_awaited()
    cache.env.stop.assert_awaited_once_with(True)
    assert not cache.env._force_template_rebuild


def test_pending_build_waits_for_same_selected_build(cache, monkeypatch):
    cache.status.side_effect = [
        SimpleNamespace(status=TemplateBuildStatus.WAITING, reason=None),
        SimpleNamespace(status=TemplateBuildStatus.BUILDING, reason=None),
        SimpleNamespace(status=TemplateBuildStatus.READY, reason=None),
    ]
    sleep = AsyncMock()
    monkeypatch.setattr(e2b.asyncio, "sleep", sleep)
    assert asyncio.run(cache.env._does_template_exist())
    assert sleep.await_count == 2
    assert len({call.args[0].build_id for call in cache.status.await_args_list}) == 1


def test_pending_wait_obeys_caller_deadline(cache):
    cache.status.return_value.status = TemplateBuildStatus.BUILDING

    async def run():
        await asyncio.wait_for(cache.env._does_template_exist(), timeout=0.01)

    with pytest.raises(TimeoutError):
        asyncio.run(run())


@pytest.mark.parametrize("forced", [False, True])
def test_locked_builder_reuses_ready_cache_unless_forced(cache, tmp_path, monkeypatch, forced):
    monkeypatch.setattr(e2b, "user_cache_path", lambda name: tmp_path)
    build = AsyncMock()
    monkeypatch.setattr(E2BEnvironment, "_create_template", build)

    async def start(self, force_build):
        await self._create_template()

    monkeypatch.setattr(TaskEnvironmentMixin, "start", start)
    asyncio.run(cache.env.start(forced))
    assert build.await_count == int(forced)
    assert not cache.env._force_template_rebuild
    assert cache.lookup.await_count == int(not forced)


def test_failed_forced_rebuild_resets_flag(cache, tmp_path, monkeypatch):
    monkeypatch.setattr(e2b, "user_cache_path", lambda name: tmp_path)
    monkeypatch.setattr(
        E2BEnvironment, "_create_template", AsyncMock(side_effect=TemplateException("build failed"))
    )

    async def start(self, force_build):
        await self._create_template()

    monkeypatch.setattr(TaskEnvironmentMixin, "start", start)
    with pytest.raises(TemplateException, match="build failed"):
        asyncio.run(cache.env.start(True))
    assert not cache.env._force_template_rebuild
