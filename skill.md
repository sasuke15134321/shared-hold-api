# Shared Hold API — Skill

SQLite-backed shared boundary storage for AI agents. Pay-per-hold via x402 USDC on Base.

## Purpose
Use Shared Hold API to store UTF-8 payloads to a persistent shared boundary and retrieve them by ID.
Useful for cross-agent data passing, boundary checkpointing, and shared state storage.

## When to use
- You need to store a payload that another agent or process will retrieve later
- You need to pass data across agent boundaries or conversation turns
- You need to checkpoint intermediate results with integrity verification
- You need a shared read-accessible store (any caller can discover and retrieve)

## When not to use
- Single-retrieval (holds are always readable multiple times — GET is non-destructive)
- Secret storage (this is a shared, discoverable boundary — not private)
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
  "created_by": "agent-001"
}
```

### GET /hold/{hold_id} (free)

Retrieve payload by ID. Non-destructive, idempotent.

### GET /hold (free)

List all stored items with metadata (no payload bytes).

## x402 payment flow (for POST /hold only)
1. Call POST /hold without payment — receive HTTP 402 with x402 requirements
2. Pay 0.005 USDC on Base (eip155:8453) via a compatible x402 client
3. Retry POST /hold with X-PAYMENT or PAYMENT-SIGNATURE header
4. Receive the hold receipt

## Key properties
- Non-destructive: GET never removes or modifies stored payload
- Idempotent reads: same hold_id always returns same payload
- SHA-256 integrity: payload is verified on every GET
- No state machine: there is no HELD/ACTIVE/RELEASED concept — everything is always readable
- GET endpoints (retrieve + discover) are always free, no payment required
