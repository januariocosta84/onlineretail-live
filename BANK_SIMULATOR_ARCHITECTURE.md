# Simulated Bank Gateway — Architecture & API Reference

**Purpose**: a fully automated, platform-mediated "Automated Bank Transfer" payment
method, built as a dev/test simulation so the full payment lifecycle (processing,
callbacks, order updates, notifications, refunds, error handling) can be exercised
before a real banking partner exists. Designed with a gateway abstraction so a real
bank API can later implement the same interface without touching business logic.

This is separate from — and does not change — the existing manual "Bank / Mobile
Transfer" method, where the buyer pays the seller directly off-platform with no
commission. The simulated gateway is commission-bearing and platform-mediated, the
same economics as the Stripe path.

---

## 1. How it fits together

```
Checkout (buyer picks "Automated Bank Transfer" + an account number)
        │
        ▼
_process_simulated_bank_checkout()  — creates Order(s) + Payment(gateway=SIMULATED_BANK)
        │
        ▼
SimulatedBankGateway.initiate()     — olretail/payment_gateways.py
        │  looks up the VirtualBankAccount, resolves a deterministic outcome,
        │  creates a SimulatedBankTransaction(status=PENDING)
        ▼
   ┌────────────────────────────────────────────────────────┐
   │ Settlement — three paths, in order of reliability:      │
   │ 1. threading.Timer (best-effort, ~SETTLE_DELAY seconds) │
   │ 2. Reconcile-on-access (buyer revisits the confirmation │
   │    page — _reconcile_payment)                           │
   │ 3. settle_simulated_bank_transactions sweep command      │
   │    (also flags overdue "always timeout" transactions)   │
   └────────────────────────────────────────────────────────┘
        │
        ▼
_process_bank_callback()  — olretail/payment_views.py — the single entrypoint
        │  that applies the outcome to Payment/Order, shared by the Timer, the
        │  sweep command, the inbound webhook, and the admin "replay" action.
        ▼
_mark_payment_succeeded() / _mark_payment_failed()
        (the SAME functions the Stripe webhook uses — order status, commission
        Transaction, SellerBalance, inventory, notifications)
```

**Why the gateway abstraction matters**: `PaymentGateway` (an ABC in
`olretail/payment_gateways.py`) defines `initiate`/`get_status`/`cancel`/`refund`.
`SimulatedBankGateway` is the only implementation today. A real bank integration
would implement the same interface and be swapped in at the one call site in
`_process_simulated_bank_checkout` — none of `_mark_payment_succeeded`,
`_mark_payment_failed`, `_process_bank_callback`, notifications, commission, or
`SellerBalance` code would need to change.

---

## 2. Deterministic test outcomes

Every outcome is reachable **deterministically** via a named virtual account (not
randomness), seeded by `manage.py seed_bank_simulator_accounts`:

| Account number | Behavior |
|---|---|
| `SIM-0001-SUCCESS` | Always succeeds |
| `SIM-0002-INSUFFICIENT` | Always declined — insufficient funds |
| `SIM-0003-CLOSED` | Closed account — rejected as invalid immediately |
| `SIM-0004-FAIL` | Always fails (generic decline) |
| `SIM-0005-TIMEOUT` | Never auto-settles — stays pending until an admin retries/settles it, or the sweep command flags it as timed out |
| `SIM-0006-DUPLICATE` | Always flagged as a duplicate transaction |

`INVALID_ACCOUNT` and `DUPLICATE` resolve instantly (no settlement delay — a real
bank rejects these immediately too). Every other outcome goes through the pending →
settled lifecycle. `CANCELLED` isn't a fixture outcome — it's reachable by
cancelling any still-pending transaction (e.g. one against `SIM-0005-TIMEOUT`) via
`cancel_order` or the admin "settle_now"/dashboard actions.

An admin can also create additional accounts, adjust balances (drives the `AUTO`
insufficient-funds check), and change an account's `forced_outcome` from
**Dashboard → Bank simulator accounts**.

---

## 3. Settlement reliability

There's no task queue (no Celery/Redis) in this project, so settlement uses the
same two-layer pattern already used for Stripe (webhook + reconcile-on-access
fallback):

- **`threading.Timer`** — a nicety for interactive local testing (resolves a few
  seconds after checkout). Explicitly best-effort: it dies on `runserver`
  autoreload and doesn't survive a process restart.
- **Reconcile-on-access** — visiting/refreshing the order confirmation page
  settles an overdue transaction inline.
- **`manage.py settle_simulated_bank_transactions`** — the reliable sweep command.
  Settles any overdue pending transaction and flags overdue "always timeout"
  transactions as `TIMEOUT`. This is what a real deployment would point a cron job
  at, and what tests should call directly instead of sleeping.
- **Admin "Settle now" / "Retry"** — forces settlement/retry synchronously from the
  transaction detail page in the dashboard.

Settings (env-configurable, see `.env.example`):

| Setting | Default | Meaning |
|---|---|---|
| `SIMULATED_BANK_SETTLE_DELAY_SECONDS` | `8` | How long a transaction stays pending before auto-settling |
| `SIMULATED_BANK_TIMEOUT_SECONDS` | `120` | How long an unresolved "always timeout" transaction sits before the sweep command flags it |
| `SIMULATED_BANK_FEE_PERCENT` / `SIMULATED_BANK_FEE_FIXED` | `0.015` / `0.10` | This gateway's own processing-fee schedule (independent of Stripe's) |
| `SIMULATED_BANK_WEBHOOK_SECRET` | — | HMAC secret for the inbound webhook signature |
| `BANK_SIMULATOR_API_KEY` | — | Static bearer token for the developer REST API |

---

## 4. Developer REST API

Plain Django views (`JsonResponse`), no DRF — matches this app's existing
hand-rolled Stripe-webhook convention. Auth: `Authorization: Bearer <BANK_SIMULATOR_API_KEY>`.

This API is independent of the marketplace checkout flow — checkout calls
`SimulatedBankGateway` directly rather than looping back through HTTP. The API
exists so the gateway can be exercised the way a real bank's API would be (curl,
Postman, or a future integration client), and so a real bank integration has a
concrete existing contract to match.

```
POST /api/bank-simulator/v1/payments/
  Headers: Authorization: Bearer <key>, Idempotency-Key: <optional>
  Body:    {"account_number": "SIM-0001-SUCCESS", "amount_cents": 11500,
            "currency": "USD", "order_reference": "ORD-..."}
  → 202 {"reference": "SIMBANK-...", "status": "pending", "created_at": ..., "settle_after": ...}
  → 402 {"reference": "SIMBANK-...", "status": "invalid_account"|"duplicate", ...}

GET  /api/bank-simulator/v1/payments/{reference}/
  → {"reference", "status", "amount_cents", "settled_at", "error_message"}

POST /api/bank-simulator/v1/payments/{reference}/cancel/
POST /api/bank-simulator/v1/payments/{reference}/refund/
  Body (optional): {"amount_cents": ...}  — only full refunds apply to orders today

GET  /api/bank-simulator/v1/accounts/{account_number}/
  → {"account_number", "account_holder_name", "bank_name", "status", "balance_cents"}
```

**Idempotency**: a repeated `POST /payments/` with the same `Idempotency-Key` and
the same request body replays the original response instead of creating a second
transaction. The same key with a *different* body is a `422`. This is a client-
retry safety net — distinct from `DUPLICATE`, which is a simulated bank-side fraud
outcome (see the `SIM-0006-DUPLICATE` fixture above).

---

## 5. Webhook

`POST /webhook/simulated-bank/` — HMAC-SHA256 signed (`X-SimBank-Signature` header,
hex digest of the raw body using `SIMULATED_BANK_WEBHOOK_SECRET`), same role as
`/webhook/stripe/`. In this simulator, the "bank" is really our own settlement
timer/sweep command calling `_process_bank_callback` directly rather than posting
HTTP requests to itself — but the endpoint is fully functional, and is what a real
bank integration would be configured to call instead.

---

## 6. Admin dashboard

**Dashboard → Bank simulator accounts**: create/manage virtual accounts, adjust
balances, set forced outcomes, activate/close/freeze.

**Dashboard → Bank simulator transactions**: list/filter every simulated
transaction (satisfies "view all simulated transactions" / "complete payment
logs"), each with:
- A full request/response event log (`GatewayEventLog` — outbound `initiate`,
  inbound `callback`/`webhook`/`timeout`, admin actions).
- **Retry** — re-runs the outcome decision against the same submitted account
  (useful after topping up a balance or changing `forced_outcome`).
- **Settle now** — forces a pending transaction to resolve immediately.
- **Replay callback** — re-applies `_process_bank_callback` for a settled
  transaction (idempotent — a no-op if already applied).
- **Refund** — reverses commission/inventory/notifications on a succeeded payment
  and credits the virtual account back.

Every action is logged to the existing dashboard `AuditLog` via `log_action`
(prefixed `bank_sim_*`), same as every other admin action in this app.

---

## 7. Known boundaries (deliberate, not bugs)

- No new `Order.status` values — failed/timeout/insufficient-funds/invalid-
  account/duplicate all leave the order `pending_payment` (retryable), identical
  to how a failed Stripe payment behaves today. The specific outcome lives on
  `SimulatedBankTransaction.status`/`error_message`.
- `select_for_update()` is a no-op on SQLite (this repo's dev database) — the
  "settle exactly once" guard is best-effort under true concurrency, same as every
  other `transaction.atomic()` block in this codebase.
- Refunds aren't wired into the `Dispute`/`DisputeResolution` flow — that flow
  doesn't execute a refund for any gateway today, Stripe included.
