"""Agent-visible transport for public MCP tools, without sandbox credentials."""

import argparse
import json
import time
import uuid
from pathlib import Path

from mcp_timeouts import transport_timeouts

ROOT = Path("/opt/harbor-mcp")
p = argparse.ArgumentParser()
p.add_argument("tool", help="Tool name, or list")
p.add_argument("arguments", nargs="?", default="{}", help="JSON object")
a = p.parse_args()
args = json.loads(a.arguments)
if not isinstance(args, dict):
    raise SystemExit("Tool arguments must be a JSON object")
ident = uuid.uuid4().hex
request = ROOT / "requests" / f"{ident}.json"
tmp = request.with_suffix(".tmp")
tmp.write_text(json.dumps({"tool": a.tool, "arguments": args}))
tmp.replace(request)
response = ROOT / "responses" / f"{ident}.json"
_, mailbox_timeout, _ = transport_timeouts(a.tool, args)
deadline = time.monotonic() + mailbox_timeout
while True:
    try:
        data = json.loads(response.read_text())
        break
    except (FileNotFoundError, json.JSONDecodeError):
        # The SDK writes response bytes asynchronously. Reading a partial file
        # must not produce a failed tool or submit the ARE action a second time.
        pass
    if time.monotonic() > deadline:
        raise SystemExit("MCP transport timed out")
    time.sleep(0.2)
print(json.dumps(data, ensure_ascii=False))
raise SystemExit(1 if data.get("isError") else 0)
