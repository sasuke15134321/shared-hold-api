# Shared Hold API v0.1

SQLite-backed shared boundary storage for AI agents. Pay-per-hold via x402 USDC on Base.

## Endpoints

| Method | Path | Cost | Description |
|--------|------|------|-------------|
| POST | /hold | 0.005 USDC | Store UTF-8 payload to shared boundary |
| GET | /hold/{id} | free | Retrieve stored payload by hold_id |
| GET | /hold | free | List all stored item metadata |
| GET | /health | free | Health check |
| GET | /.well-known/x402.json | free | x402 endpoint discovery |
| GET | /ai-agent-policy.json | free | Agent policy |
| GET | /llms.txt | free | LLM-readable description |
| GET | /skill.md | free | Skill description |
| GET | /openapi.yaml | free | OpenAPI spec |

## Key design decision

There is no "restore" or "release" endpoint. GET /hold/{id} is non-destructive and idempotent —
the same hold_id always returns the same payload. Payloads are always in HELD state and readable
any number of times.

## Quick start (local, TEST_MODE)

```bash
cd shared_hold
pip install -r requirements.txt
TEST_MODE=true uvicorn main:app --reload
```

Store:
```bash
curl -X POST http://localhost:8000/hold \
  -H "Content-Type: application/json" \
  -d '{"payload": "hello from agent", "created_by": "agent-001"}'
```

Retrieve (use hold_id from above response):
```bash
curl http://localhost:8000/hold/<hold_id>
```

List all:
```bash
curl http://localhost:8000/hold
```

## Payment flow

Without a valid X-PAYMENT header, POST /hold returns HTTP 402 with x402 v2 requirements:
- Network: Base (eip155:8453)
- Asset: USDC (0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)
- Amount: 5000 (0.005 USDC in micro-units)
- Recipient: 0x60c402878EfcEcAe5733A88075328Aa2320C39BE

GET endpoints always return 200 without any payment.

## Core

Core file: `../shared_hold.py` (SharedHold, HoldReceipt)
Core is imported at runtime — do not modify it.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| WALLET_ADDRESS | 0x60c... | Payment recipient |
| PRICE_USDC | 0.005 | Price per hold |
| SHARED_HOLD_DB_PATH | ./shared_hold.db | SQLite database path |
| CDP_API_KEY_ID | | CDP Facilitator key ID |
| CDP_API_KEY_SECRET | | CDP Facilitator key secret |
| FACILITATOR_PRIVATE_KEY | | Fallback on-chain facilitator key |
| TEST_MODE | false | Skip payment verification (dev only) |
| PORT | 8000 | Server port |

## Render deployment note

On Render free tier, the SQLite database is ephemeral (lost on restart).
For persistence, use a Render Disk and set SHARED_HOLD_DB_PATH to the mounted path.
