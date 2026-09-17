#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared Hold API v0.1
SQLite-backed shared boundary storage for AI agents. Pay-per-hold via x402.
"""
import os, sys, json, base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from typing import Optional

from payment_verifier import PaymentVerifier
from shared_hold import SharedHold

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x60c402878EfcEcAe5733A88075328Aa2320C39BE")
PRICE_USDC = os.getenv("PRICE_USDC", "0.005")
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
DB_PATH = os.getenv("SHARED_HOLD_DB_PATH", str(Path(__file__).parent / "shared_hold.db"))

_NETWORK = "eip155:8453"
_USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

app = FastAPI(
    title="Shared Hold API",
    version="0.1.0",
    description=(
        "SQLite-backed shared boundary storage for AI agents. "
        "POST /hold stores a UTF-8 payload (paid: 0.005 USDC). "
        "GET /hold/{id} retrieves by hold_id (free). "
        "GET /hold lists all stored item metadata (free). "
        "Payload is stored with SHA-256 integrity verification. "
        "Non-destructive: GET never removes or transitions the payload state."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

payment_verifier = PaymentVerifier()
_core = SharedHold(DB_PATH)


def _payment_required_body(method: str, url: str) -> dict:
    amount_units = str(round(float(PRICE_USDC) * 1_000_000))
    return {
        "x402Version": 2,
        "error": "Payment required",
        "resource": {
            "url": url,
            "method": method,
            "description": "Store payload to Shared Hold boundary — 0.005 USDC per successful hold",
            "mimeType": "application/json",
        },
        "accepts": [{
            "scheme": "exact",
            "network": _NETWORK,
            "amount": amount_units,
            "asset": _USDC_ADDRESS,
            "payTo": WALLET_ADDRESS,
            "maxTimeoutSeconds": 300,
            "extra": {"name": "USD Coin", "version": "2"},
            "resource": {"method": method, "mimeType": "application/json"},
        }],
    }


class HoldRequest(BaseModel):
    payload: str = Field(
        ...,
        description="UTF-8 text to store. Encoded as bytes internally with SHA-256 integrity.",
    )
    created_by: str = Field(
        ...,
        min_length=1,
        description="Identifier for the caller (agent ID, name, or any non-empty string).",
    )


class HoldReceiptResponse(BaseModel):
    hold_id: str
    content_hash: str
    size: int
    created_at: str
    created_by: str


@app.post(
    "/hold",
    response_model=HoldReceiptResponse,
    summary="Hold — Store payload to shared boundary (paid: 0.005 USDC)",
    description=(
        "Stores UTF-8 payload as bytes in the shared SQLite boundary. "
        "Returns a receipt with hold_id, SHA-256 content_hash, size, and created_at timestamp. "
        "Charged at 0.005 USDC per successful hold via x402."
    ),
    responses={402: {"description": "Payment Required — include X-PAYMENT or PAYMENT-SIGNATURE header"}},
    tags=["Core"],
)
async def hold(payload: HoldRequest, request: Request):
    if not TEST_MODE:
        payment_header = (
            request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("X-PAYMENT")
        )
        if not payment_header:
            body = _payment_required_body("POST", str(request.url))
            return JSONResponse(
                status_code=402,
                content=body,
                headers={"Payment-Required": base64.b64encode(json.dumps(body).encode()).decode()},
            )
        is_valid = await payment_verifier.verify_payment(payment_header, WALLET_ADDRESS, PRICE_USDC)
        if not is_valid:
            raise HTTPException(status_code=402, detail="Payment verification failed")

    try:
        data = payload.payload.encode("utf-8")
        receipt = _core.hold(data, created_by=payload.created_by)
        return {
            "hold_id": receipt.hold_id,
            "content_hash": receipt.content_hash,
            "size": receipt.size,
            "created_at": receipt.created_at,
            "created_by": receipt.created_by,
        }
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/hold/{hold_id}",
    summary="Get — Retrieve stored payload by ID (free)",
    description=(
        "Returns the stored UTF-8 payload for the given hold_id. "
        "Free, non-destructive, and idempotent — same hold_id always returns the same payload."
    ),
    tags=["Core"],
)
async def get_hold(hold_id: str):
    try:
        raw = _core.get(hold_id)
        return {"hold_id": hold_id, "payload": raw.decode("utf-8", errors="replace")}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"hold_id not found: {hold_id}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/hold",
    summary="Discover — List all stored items (free)",
    description=(
        "Returns metadata for all stored items: hold_id, created_at, created_by, content_hash, size. "
        "Payload bytes are not included. Free, no payment required."
    ),
    tags=["Core"],
)
async def discover():
    rows = _core.discover()
    return {
        "items": [
            {
                "hold_id": r[0],
                "created_at": r[1],
                "created_by": r[2],
                "content_hash": r[3],
                "size": r[4],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@app.get("/health", include_in_schema=False)
async def health():
    return {
        "status": "healthy",
        "test_mode": TEST_MODE,
        "version": "0.1.0",
        "wallet_configured": bool(os.getenv("WALLET_ADDRESS")),
        "cdp_configured": bool(os.getenv("CDP_API_KEY_ID") and os.getenv("CDP_API_KEY_SECRET")),
        "db_path": DB_PATH,
    }


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Shared Hold API",
        "version": "0.1.0",
        "description": "SQLite-backed shared boundary storage for AI agents",
        "endpoints": {
            "hold":     "POST /hold (paid: 0.005 USDC per successful hold)",
            "get":      "GET /hold/{id} (free)",
            "discover": "GET /hold (free)",
            "health":   "GET /health (free)",
            "discovery": "GET /.well-known/x402.json (free)",
        },
        "network": "base-mainnet",
        "currency": "USDC",
    }


@app.get("/.well-known/x402.json", include_in_schema=False)
async def x402_discovery():
    return {
        "version": 1,
        "endpoints": [{
            "path": "/hold",
            "method": "POST",
            "price": PRICE_USDC,
            "currency": "USDC",
            "network": "base",
            "description": "Store payload to Shared Hold boundary",
            "category": "storage",
            "tags": ["storage", "hold", "boundary", "ai", "agents"],
        }],
    }


@app.get("/.well-known/ai-agent-policy", include_in_schema=False)
async def ai_agent_policy():
    with open(Path(__file__).parent / "ai-agent-policy.json") as f:
        return json.load(f)


@app.get("/ai-agent-policy.json", include_in_schema=False)
async def ai_agent_policy_json():
    with open(Path(__file__).parent / "ai-agent-policy.json") as f:
        return json.load(f)


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    return PlainTextResponse(open(Path(__file__).parent / "llms.txt").read())


@app.get("/skill.md", include_in_schema=False)
async def skill_md():
    return PlainTextResponse(open(Path(__file__).parent / "skill.md").read())


@app.get("/openapi.yaml", include_in_schema=False)
async def openapi_yaml_endpoint():
    return PlainTextResponse(
        open(Path(__file__).parent / "openapi.yaml").read(), media_type="text/yaml"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
