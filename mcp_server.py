#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared Hold API — MCP Server
Exposes POST /hold, GET /hold/{id}, GET /hold as MCP tools via stdio transport.
Requires: pip install mcp httpx python-dotenv
"""
import asyncio, json, os, sys
from pathlib import Path

try:
    import httpx
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("Install: pip install mcp httpx", file=sys.stderr)
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

BASE_URL = os.getenv("SHARED_HOLD_URL", "http://localhost:8000")
API_KEY  = os.getenv("X_PAYMENT", "")

server = Server("shared-hold-api")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="hold",
            description=(
                "Store a UTF-8 payload to the shared boundary. "
                "Paid: 0.005 USDC per successful hold via x402. "
                "Returns hold_id, content_hash, size, created_at, created_by."
            ),
            inputSchema={
                "type": "object",
                "required": ["payload", "created_by"],
                "properties": {
                    "payload": {
                        "type": "string",
                        "description": "UTF-8 text to store",
                    },
                    "created_by": {
                        "type": "string",
                        "description": "Caller identifier (non-empty string)",
                    },
                    "x_payment": {
                        "type": "string",
                        "description": "x402 v2 payment header value (base64-encoded signed payment)",
                    },
                },
            },
        ),
        types.Tool(
            name="get_hold",
            description=(
                "Retrieve a stored payload by hold_id. Free, non-destructive, idempotent. "
                "Returns {hold_id, payload}. 404 if not found."
            ),
            inputSchema={
                "type": "object",
                "required": ["hold_id"],
                "properties": {
                    "hold_id": {
                        "type": "string",
                        "description": "The hold_id returned by the hold tool",
                    },
                },
            },
        ),
        types.Tool(
            name="discover_holds",
            description=(
                "List all stored items with metadata (hold_id, created_at, created_by, content_hash, size). "
                "Free. Payload bytes are not included."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        if name == "hold":
            x_payment = arguments.pop("x_payment", API_KEY)
            headers = {"Content-Type": "application/json"}
            if x_payment:
                headers["X-PAYMENT"] = x_payment
            resp = await client.post(f"{BASE_URL}/hold", json=arguments, headers=headers)
        elif name == "get_hold":
            hold_id = arguments["hold_id"]
            resp = await client.get(f"{BASE_URL}/hold/{hold_id}")
        elif name == "discover_holds":
            resp = await client.get(f"{BASE_URL}/hold")
        else:
            raise ValueError(f"Unknown tool: {name}")

    return [types.TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
