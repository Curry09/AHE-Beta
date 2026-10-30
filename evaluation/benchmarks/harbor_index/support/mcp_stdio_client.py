"""Expose the existing public ARE mailbox as a native MCP stdio server."""

import json
import subprocess
import sys

try:
    from .mcp_timeouts import transport_timeouts
except ImportError:  # Standalone script uploaded to the task sandbox.
    from mcp_timeouts import transport_timeouts


def forward(tool, arguments):
    result = subprocess.run(
        [sys.executable, "/opt/harbor-mcp/client.py", tool, json.dumps(arguments)],
        capture_output=True,
        text=True,
        timeout=transport_timeouts(tool, arguments)[2],
        check=False,
    )
    return json.loads(result.stdout)


def main():
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        params = request.get("params", {})
        try:
            match request.get("method"):
                case "initialize":
                    result = {
                        "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "official-are-e2b-transport", "version": "1"},
                    }
                case "tools/list":
                    result = forward("list", {})
                case "tools/call":
                    result = forward(params["name"], params.get("arguments", {}))
                    if "content" not in result:
                        result = {
                            "isError": True,
                            "content": [{"type": "text", "text": "Official ARE transport failed"}],
                        }
                case "ping":
                    result = {}
                case _:
                    raise ValueError("Unsupported MCP method")
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as error:  # noqa: BLE001 - never expose provider credentials
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32603, "message": type(error).__name__},
            }
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
