"""Exercise real provider constructors with the pinned framework's SDK options."""

import asyncio

import pytest
from anthropic import Anthropic, AsyncAnthropic
from nexau.archs.llm.llm_config import LLMConfig
from openai import AsyncOpenAI, OpenAI


@pytest.mark.parametrize(
    ("api_type", "client_class"),
    [
        ("openai_chat_completion", OpenAI),
        ("anthropic_chat_completion", Anthropic),
    ],
)
def test_sync_provider_accepts_nexau_timeout(api_type, client_class):
    config = LLMConfig(
        model="constructor-probe",
        api_type=api_type,
        api_key="constructor-probe",
        base_url="https://example.invalid",
        timeout=300,
    )
    with client_class(**config.to_client_kwargs()) as client:
        assert client.api_key == "constructor-probe"


@pytest.mark.parametrize(
    ("api_type", "client_class"),
    [
        ("openai_chat_completion", AsyncOpenAI),
        ("anthropic_chat_completion", AsyncAnthropic),
    ],
)
def test_async_provider_accepts_nexau_timeout(api_type, client_class):
    config = LLMConfig(
        model="constructor-probe",
        api_type=api_type,
        api_key="constructor-probe",
        base_url="https://example.invalid",
        timeout=300,
    )

    async def probe():
        async with client_class(**config.to_client_kwargs()) as client:
            assert client.api_key == "constructor-probe"

    asyncio.run(probe())
