"""Shared Hold API wrapper tests — runs with TEST_MODE=true (no payment required)."""
import os, sys, tempfile
os.environ["TEST_MODE"] = "true"

import pytest
from fastapi.testclient import TestClient

# One temp DB for the shared client — avoids module re-import side effects
_tmp_db = tempfile.mktemp(suffix=".db")
os.environ["SHARED_HOLD_DB_PATH"] = _tmp_db
from main import app, _core as _main_core  # noqa: E402  (import after env setup)
import main as _main_module

client = TestClient(app)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def restore_test_mode():
    _main_module.TEST_MODE = True
    yield
    _main_module.TEST_MODE = True


# ── Tests ───────────────────────────────────────────────────────────────────

def test_root():
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "Shared Hold API"
    assert data["version"] == "0.1.0"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert r.json()["test_mode"] is True


def test_x402_discovery():
    r = client.get("/.well-known/x402.json")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == 1
    assert any(e["path"] == "/hold" and e["method"] == "POST" for e in data["endpoints"])


def test_ai_agent_policy():
    r = client.get("/ai-agent-policy.json")
    assert r.status_code == 200
    assert r.json()["agent_name"] == "Shared Hold API"


def test_hold_basic():
    r = client.post("/hold", json={"payload": "hello world", "created_by": "test-agent"})
    assert r.status_code == 200
    data = r.json()
    assert "hold_id" in data
    assert "content_hash" in data
    assert data["size"] == len(b"hello world")
    assert data["created_by"] == "test-agent"


def test_hold_receipt_fields():
    r = client.post("/hold", json={"payload": "test payload", "created_by": "tester"})
    data = r.json()
    for key in ["hold_id", "content_hash", "size", "created_at", "created_by"]:
        assert key in data, f"Missing field: {key}"


def test_get_hold():
    receipt = client.post("/hold", json={
        "payload": "retrieve me", "created_by": "agent-x"
    }).json()
    r = client.get(
        f"/hold/{receipt['hold_id']}",
        headers={"X-Hold-Token": receipt["access_token"]},
    )
    assert r.status_code == 200
    assert r.json()["payload"] == "retrieve me"



def test_get_hold_idempotent():
    receipt = client.post("/hold", json={
        "payload": "idempotent", "created_by": "a"
    }).json()
    url = f"/hold/{receipt['hold_id']}"
    headers = {"X-Hold-Token": receipt["access_token"]}
    r1 = client.get(url, headers=headers)
    r2 = client.get(url, headers=headers)
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()



def test_get_hold_not_found():
    r = client.get("/hold/nonexistent-hold-id-xyz")
    assert r.status_code == 404


def test_discover_returns_list():
    r = client.get("/hold")
    assert r.status_code == 200
    data = r.json()
    assert data["hold_supported"] is True
    assert data["get_requires_token"] is True
    assert "items" not in data
    assert "total_available" not in data



def test_discover_includes_held_items():
    receipt = client.post("/hold", json={
        "payload": "private item", "created_by": "private-agent"
    }).json()
    r = client.get("/hold")
    assert r.status_code == 200
    assert receipt["hold_id"] not in r.text
    assert receipt["access_token"] not in r.text
    assert "private-agent" not in r.text



def test_discover_metadata_fields():
    r = client.get("/hold")
    assert r.status_code == 200
    for field in ["hold_id", "created_at", "created_by",
                  "content_hash", "size", "items", "total"]:
        assert field not in r.json()



def test_discover_no_payload_bytes():
    client.post("/hold", json={
        "payload": "SECRET_PAYLOAD_MARKER", "created_by": "a"
    })
    r = client.get("/hold")
    assert r.status_code == 200
    assert "SECRET_PAYLOAD_MARKER" not in r.text



def test_discover_respects_limit_and_offset():
    r = client.get("/hold?limit=2&offset=1")
    assert r.status_code == 200
    assert "items" not in r.json()
    assert "limit" not in r.json()
    assert "offset" not in r.json()



def test_discover_rejects_oversized_limit():
    r = client.get("/hold?limit=101")
    assert r.status_code == 200
    assert "items" not in r.json()



def test_hold_unicode():
    receipt = client.post("/hold", json={
        "payload": "日本語テスト", "created_by": "unicode-agent"
    }).json()
    r = client.get(
        f"/hold/{receipt['hold_id']}",
        headers={"X-Hold-Token": receipt["access_token"]},
    )
    assert r.status_code == 200
    assert r.json()["payload"] == "日本語テスト"



def test_hold_requires_payment_without_test_mode(monkeypatch):
    import base64
    import json

    from x402.schemas.responses import SupportedResponse

    def fake_get_supported():
        return SupportedResponse(
            kinds=[{
                "x402Version": 2,
                "scheme": "exact",
                "network": "eip155:8453",
            }],
            extensions=[],
            signers={},
        )

    monkeypatch.setattr(
        _main_module._facilitator,
        "get_supported",
        fake_get_supported,
    )

    _main_module.TEST_MODE = False
    r = client.post("/hold", json={"payload": "pay me", "created_by": "a"})

    assert r.status_code == 402

    payment_required = r.headers.get("Payment-Required")
    assert payment_required is not None

    data = json.loads(
        base64.b64decode(payment_required).decode("utf-8")
    )

    assert data["x402Version"] == 2
    assert len(data["accepts"]) == 1

    requirement = data["accepts"][0]
    assert requirement["scheme"] == "exact"
    assert requirement["network"] == "eip155:8453"
    assert requirement["amount"] == "5000"
    assert requirement["payTo"].lower() == _main_module.WALLET_ADDRESS.lower()

    assert "extensions" in data
    assert "bazaar" in data["extensions"]


def test_get_hold_free_no_payment_header():
    receipt = client.post("/hold", json={
        "payload": "free retrieval", "created_by": "test-agent"
    }).json()
    r = client.get(
        f"/hold/{receipt['hold_id']}",
        headers={"X-Hold-Token": receipt["access_token"]},
    )
    assert r.status_code == 200
    assert r.json()["payload"] == "free retrieval"



def test_discover_free_no_payment_header():
    _main_module.TEST_MODE = False
    r = client.get("/hold")
    assert r.status_code == 200


def test_request_body_over_2mb_rejected():
    _main_module.TEST_MODE = True
    oversized = b"x" * (_main_module.MAX_REQUEST_BODY_BYTES + 1)
    r = client.post(
        "/hold",
        content=oversized,
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


def test_request_body_over_2mb_without_content_length_rejected():
    import asyncio

    downstream_called = False
    sent = []

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True

        while True:
            message = await receive()
            if (
                message["type"] == "http.request"
                and not message.get("more_body", False)
            ):
                break

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send({
            "type": "http.response.body",
            "body": b"OK",
        })

    app = _main_module.RequestBodyLimitMiddleware(
        downstream,
        max_body_size=_main_module.MAX_REQUEST_BODY_BYTES,
    )

    chunks = [
        {
            "type": "http.request",
            "body": b"x" * (1024 * 1024),
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b"x" * (1024 * 1024),
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b"x",
            "more_body": False,
        },
    ]

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/hold",
        "headers": [],
    }

    asyncio.run(app(scope, receive, send))

    statuses = [
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    ]

    assert downstream_called is True
    assert statuses == [413]


def test_missing_access_token_rejected():
    receipt = client.post("/hold", json={
        "payload": "protected", "created_by": "security-test"
    }).json()
    r = client.get(f"/hold/{receipt['hold_id']}")
    assert r.status_code == 404


def test_wrong_access_token_rejected():
    receipt = client.post("/hold", json={
        "payload": "protected", "created_by": "security-test"
    }).json()
    r = client.get(
        f"/hold/{receipt['hold_id']}",
        headers={"X-Hold-Token": "incorrect-token"},
    )
    assert r.status_code == 404


def test_access_token_not_stored_in_plaintext():
    import sqlite3
    from contextlib import closing

    receipt = client.post("/hold", json={
        "payload": "protected", "created_by": "security-test"
    }).json()

    with closing(sqlite3.connect(_tmp_db)) as con:
        row = con.execute(
            "SELECT access_token_hash FROM holds WHERE hold_id=?",
            (receipt["hold_id"],),
        ).fetchone()

    assert row is not None
    assert row[0] != receipt["access_token"]
    assert len(row[0]) == 64
