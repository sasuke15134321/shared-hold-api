# Shared Hold API — Skill

SQLite-backed shared boundary storage for AI agents. Pay-per-hold via x402 USDC on Base.

## Purpose
Use Shared Hold API to store UTF-8 payloads to a persistent shared boundary and retrieve them by ID.
Useful for cross-agent data passing, boundary checkpointing, and shared state storage.

## When to use
- You need to store a payload that another agent or process will retrieve later
- You need to pass data across agent boundaries or conversation turns
- You need to checkpoint intermediate results with integrity verification
- You need capability-controlled retrieval across agents or processes

## When not to use
- Single-retrieval (holds are always readable multiple times — GET is non-destructive)
- Storing highly sensitive secrets without additional encryption and key management
- Replacing a database or file system for large-scale structured data

## Endpoints

### POST /hold (paid: 0.005 USDC)

Store a UTF-8 payload.

#### Example request
```json
{
  "payload": "Agent checkpoint: task complete at 2026-09-17T12:00:00Z",
  "created_by": "agent-001"
}
```

#### Example response
```json
{
  "hold_id": "a3f2c1b0...",
  "content_hash": "sha256hex...",
  "size": 52,
  "created_at": "2026-09-17T12:00:00.000000+00:00",
  "created_by": "agent-001",
  "access_token": "<one-time-secret-token>"
}
```

### GET /hold/{hold_id} (free)

Retrieve with hold_id and X-Hold-Token (the access_token issued by POST /hold). Missing or invalid tokens return 404. Authorized reads are non-destructive and idempotent.

### GET /hold (free)

Returns public service capabilities only: service, hold_supported, get_requires_token, retrieval_payment_required. No stored IDs, metadata, counts, or payloads.

## x402 payment flow (for POST /hold only)
1. Call POST /hold without payment — receive HTTP 402 with x402 requirements
2. Pay 0.005 USDC on Base (eip155:8453) via a compatible x402 client
3. Retry POST /hold with X-PAYMENT or PAYMENT-SIGNATURE header
4. Receive the hold receipt and securely retain access_token for future retrieval

## Key properties
- Non-destructive: GET never removes or modifies stored payload
- Idempotent authorized reads: same hold_id and valid token return the same payload
- SHA-256 integrity: payload is verified on every GET
- No restore/release state transition; retrieval requires a valid capability token
- GET endpoints (retrieve + discover) are always free, no payment required
