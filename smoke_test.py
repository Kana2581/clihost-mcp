"""End-to-end smoke test: spin up the server in-process, drive it via the
FastMCP Client, exercise list_adapters and claude_run."""

import asyncio
import json

from fastmcp import Client

from clihost_mcp.config import Config
from clihost_mcp.server import build_server


async def main():
    config = Config()
    mcp = build_server(config)

    async with Client(mcp) as client:
        print("=" * 60)
        print("claude_run (real CLI call)")
        print("=" * 60)
        result = await client.call_tool(
            "claude_run",
            {"prompt": "Reply with exactly the word PONG and nothing else.", "timeout_sec": 120},
        )
        out = result.structured_content
        print(f"exit_code: {out.get('exit_code')}")
        print(f"duration_ms: {out.get('duration_ms')}")
        print(f"timed_out: {out.get('timed_out')}")
        print(f"error: {out.get('error')}")
        if out.get("parsed"):
            print("--- parsed ---")
            print(json.dumps(out["parsed"], indent=2, ensure_ascii=False))
        print("--- stdout (first 1500 chars) ---")
        print((out.get("stdout") or "")[:1500])
        print("--- stderr (first 500 chars) ---")
        print((out.get("stderr") or "")[:500])


if __name__ == "__main__":
    asyncio.run(main())
