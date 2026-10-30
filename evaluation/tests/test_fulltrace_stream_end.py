"""Closing a stream after [DONE] must not be recorded as an API interruption."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("done", [True, False])
@pytest.mark.parametrize("asynchronous", [True, False])
def test_stream_close_preserves_terminal_marker_and_partial_bytes(tmp_path, done, asynchronous):
    code = r"""
import asyncio, gc, json, sys
from pathlib import Path
import httpx
from evaluation.harness.fulltrace import install
root=Path(sys.argv[1]); done=sys.argv[2]=='True'; asynchronous=sys.argv[3]=='True'
install('actor',root)
body=b'data: {"choices":[{"delta":{"content":"kept in full"}}]}\n\n'
if done: body+=b'data: [DONE]\n\n'
class Sync(httpx.SyncByteStream):
    def __iter__(self):
        yield body
        yield b'\n'
class Async(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield body
        yield b'\n'
async def main():
    transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=Async()))
    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream('POST','https://fixture.invalid/v1/chat/completions',json={}) as response:
            iterator=response.aiter_bytes()
            assert await anext(iterator)==body
            await iterator.aclose()
if asynchronous: asyncio.run(main())
else:
    transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=Sync()))
    with httpx.Client(transport=transport) as client:
        with client.stream('POST','https://fixture.invalid/v1/chat/completions',json={}) as response:
            iterator=response.iter_bytes()
            assert next(iterator)==body
            iterator.close()
gc.collect()
"""
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), str(done), str(asynchronous)],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    events = [json.loads(s) for s in (tmp_path / "events.jsonl").read_text().splitlines()]
    closes = [e for e in events if e["event"] in {"response_completed", "response_interrupted"}]
    assert len(closes) == 1
    assert closes[0]["event"] == ("response_completed" if done else "response_interrupted")
    assert closes[0]["terminal_marker_seen"] is done
    assert b"kept in full" in next(tmp_path.glob("*.response.body")).read_bytes()
