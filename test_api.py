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
    hold_r = client.post("/hold", json={"payload": "retrieve me", "created_by": "agent-x"})
    hold_id = hold_r.json()["hold_id"]
    r = client.get(f"/hold/{hold_id}")
    assert r.status_code == 200
    assert r.json()["payload"] == "retrieve me"
    assert r.json()["hold_id"] == hold_id


def test_get_hold_idempotent():
    hold_r = client.post("/hold", json={"payload": "idempotent", "created_by": "a"})
    hold_id = hold_r.json()["hold_id"]
    r1 = client.get(f"/hold/{hold_id}")
    r2 = client.get(f"/hold/{hold_id}")
    assert r1.json()["payload"] == r2.json()["payload"]


def test_get_hold_not_found():
    r = client.get("/hold/nonexistent-hold-id-xyz")
    assert r.status_code == 404


def test_discover_returns_list():
    r = client.get("/hold")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert "total_available" in data
    assert isinstance(data["items"], list)
    assert data["total"] == len(data["items"])
    assert data["total"] <= 100


def test_discover_includes_held_items():
    client.post("/hold", json={"payload": "item A", "created_by": "a"})
    client.post("/hold", json={"payload": "item B", "created_by": "b"})
    r = client.get("/hold")
    assert r.status_code == 200
    assert r.json()["total_available"] >= 2


def test_discover_metadata_fields():
    client.post("/hold", json={"payload": "meta test", "created_by": "c"})
    r = client.get("/hold")
    for item in r.json()["items"]:
        for key in ["hold_id", "created_at", "created_by", "content_hash", "size"]:
            assert key in item


def test_discover_no_payload_bytes():
    r = client.get("/hold")
    for item in r.json()["items"]:
        assert "payload" not in item


def test_discover_respects_limit_and_offset():
    for i in range(5):
        client.post("/hold", json={"payload": f"page-{i}", "created_by": "pager"})
    r = client.get("/hold?limit=2&offset=1")
    assert r.status_code == 200
    data = r.json()
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert data["total"] <= 2
    assert data["total_available"] >= data["total"]


def test_discover_rejects_oversized_limit():
    r = client.get("/hold?limit=101")
    assert r.status_code == 422


def test_hold_unicode():
    r = client.post("/hold", json={"payload": "日本語テスト🎌", "created_by": "unicode-agent"})
    assert r.status_code == 200
    hold_id = r.json()["hold_id"]
    g = client.get(f"/hold/{hold_id}")
    assert g.json()["payload"] == "日本語テスト🎌"


def test_hold_requires_payment_without_test_mode():
    _main_module.TEST_MODE = False
    r = client.post("/hold", json={"payload": "pay me", "created_by": "a"})
    assert r.status_code == 402
    data = r.json()
    assert data.get("x402Version") == 2
    assert "accepts" in data


def test_get_hold_free_no_payment_header():
    _main_module.TEST_MODE = True
    hold_r = client.post("/hold", json={"payload": "free read", "created_by": "b"})
    hold_id = hold_r.json()["hold_id"]
    _main_module.TEST_MODE = False
    r = client.get(f"/hold/{hold_id}")
    assert r.status_code == 200


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
