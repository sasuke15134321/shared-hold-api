#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared Hold API — MCP Server
stdio / Streamable HTTP dual transport via FastMCP.
"""
import os, json
import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("SHARED_HOLD_URL", "https://shared-hold-api.onrender.com").rstrip("/")
PAYMENT_TOKEN = os.getenv("MCP_PAYMENT_TOKEN", "")

mcp = FastMCP("Shared Hold API")


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if PAYMENT_TOKEN:
        h["PAYMENT-SIGNATURE"] = PAYMENT_TOKEN
    return h


@mcp.tool()
async def hold(payload: str, created_by: str) -> str:
    """
    Store a UTF-8 payload to the shared boundary (0.005 USDC).
    Returns hold_id, content_hash, size, created_at, created_by.

    Args:
        payload:    UTF-8 text to store
        created_by: Caller identifier (non-empty string)
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/hold",
            json={"payload": payload, "created_by": created_by},
            headers=_headers(),
        )
        if resp.status_code == 402:
            return json.dumps({"error": "Payment Required (x402)", "x402": resp.json()}, ensure_ascii=False)
        resp.raise_for_status()
        return json.dumps(resp.json(), ensure_ascii=False, indent=2)


@mcp.tool()
async def get(hold_id: str) -> str:
    """
    Retrieve a stored payload by hold_id. Free, non-destructive, idempotent.
    Returns {hold_id, payload}. Returns error if not found.

    Args:
        hold_id: The hold_id returned by the hold tool
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{BASE_URL}/hold/{hold_id}")
        if resp.status_code == 404:
            return json.dumps({"error": f"hold_id not found: {hold_id}"}, ensure_ascii=False)
        resp.raise_for_status()
        return json.dumps(resp.json(), ensure_ascii=False, indent=2)


@mcp.tool()
async def discover() -> str:
    """
    List all stored items with metadata (hold_id, created_at, created_by, content_hash, size).
    Free. Payload bytes are not included.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{BASE_URL}/hold")
        resp.raise_for_status()
        return json.dumps(resp.json(), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
