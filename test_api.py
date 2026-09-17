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
    assert isinstance(data["items"], list)
    assert data["total"] == len(data["items"])


def test_discover_includes_held_items():
    client.post("/hold", json={"payload": "item A", "created_by": "a"})
    client.post("/hold", json={"payload": "item B", "created_by": "b"})
    r = client.get("/hold")
    assert r.status_code == 200
    assert r.json()["total"] >= 2


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
