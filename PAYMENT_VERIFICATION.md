# Bank-Transfer Payment Verification — Architecture & Fraud Prevention

**Purpose**: the manual "Bank / Mobile Transfer" payment method (buyer pays the
seller directly, off-platform, no commission — see `BANK_SIMULATOR_ARCHITECTURE.md`
for how this differs from the platform-mediated automated gateway) previously had
zero evidence attached to it: "I've sent payment" and "Confirm payment received"
were bare button clicks with nothing to back either claim. This document covers
what replaced that: receipt capture, fraud-signal flagging, an explicit seller
denial path, an admin dispute-resolution queue, and an auto-escalation safety net
for a seller who simply never responds.

Two failure modes this was built to close:
1. **A seller falsely denies receiving a real payment** — a buyer previously had
   no recourse beyond hoping the seller eventually clicked confirm.
2. **A buyer submits a fake/edited receipt** — nothing previously stopped a reused
   or doctored screenshot from being accepted as sufficient evidence.

---

## 1. How it fits together

```
Buyer clicks "I've sent payment" (mark_payment_sent)
        │  now a real form (PaymentProofForm), not a bare click:
        │  receipt image + reference number + claimed amount, all required
        ▼
Server-side fraud-signal checks (all soft signals, not proof of tampering):
  - claimed amount ≠ order total           → payment_flagged
  - SHA-256 of receipt already used         → payment_flagged
    on a different order (reused evidence)
  - reference number already used           → payment_flagged
    on a different order
        │
        ▼
Order.status = PAYMENT_REPORTED  (unchanged from before)
        │
        ├─────────────────────────────┬──────────────────────────────┐
        ▼                              ▼                              ▼
Seller confirms                Seller denies                  Seller never
(confirm_payment_received,     (deny_payment_received,         responds
unchanged) →                   NEW — was previously            (escalate_stale_payment_
_mark_bank_transfer_paid()     impossible to express) →         claims mgmt command,
                                Dispute(reason=                  run daily) →
                                PAYMENT_NOT_RECEIVED,            Dispute(reason=
                                status=UNDER_REVIEW)             PAYMENT_NO_RESPONSE,
                                                                  status=UNDER_REVIEW)
                                        │                              │
                                        └──────────────┬───────────────┘
                                                        ▼
                                    Admin reviews at /dashboard/payment-disputes/
                                    — sees the receipt, reference/amount, any
                                    auto-flag reason, the seller's denial reason
                                    (if any), and each party's prior track record
                                    on this exact kind of dispute
                                                        │
                                        ┌───────────────┴───────────────┐
                                        ▼                                ▼
                                    Approve                           Reject
                                    → _mark_bank_transfer_paid()       → Order.status = CANCELLED
                                    (the SAME function the seller's
                                    own confirm click calls)
```

**Why the effect function matters**: `_mark_bank_transfer_paid()` in
`olretail/payment_views.py` is the single place that actually flips an order to
Paid, decrements stock, and clears the cart. It's called from exactly two places —
the seller's own confirm click, and an admin's dispute approval — so there is only
ever one code path with those side effects, never two that could drift apart.

---

## 2. Evidence captured (`Order` fields)

| Field | Purpose |
|---|---|
| `payment_proof` | The receipt/screenshot image itself |
| `payment_reference` | Buyer-entered bank/mobile transfer reference number |
| `payment_amount_claimed` | Buyer-entered amount sent (compared against `order.total`) |
| `payment_proof_hash` | SHA-256 of the uploaded image — powers duplicate detection |
| `payment_flagged` / `payment_flag_reason` | Set automatically when a signal fires; shown to the seller and to admin, never blocks the seller's own confirm |

## 3. Fraud signals — what they catch, and what they don't

The automatic checks (amount mismatch, reused receipt hash, reused reference
number) catch the **lazy/repeat** fraud case: someone reusing one real screenshot
or reference number across multiple fake claims. They do **not** prove an image is
unedited — nothing server-side can. EXIF metadata was deliberately *not* used as a
signal: legitimate phone screenshots routinely have no EXIF data at all, so its
absence isn't evidence of tampering, and relying on it would flag honest buyers as
often as dishonest ones.

This is a known, accepted limitation, not an oversight: closing the "one
convincingly edited image, never reused" gap requires real bank API integration,
which is out of scope here (see §5).

## 4. Trust signals on the admin dispute screen

Computed live from existing `Dispute` data, not a separate scoring system to
maintain:
- **Seller's prior wrongful denials** — times this seller denied a payment that an
  admin later confirmed (`DisputeResolution.PAYMENT_CONFIRMED`).
- **Buyer's prior unverified claims** — times this buyer's payment claim was
  rejected as unverifiable (`DisputeResolution.PAYMENT_REJECTED`).

These are cheap `Dispute.objects.filter(...).count()` queries computed per-row in
`dashboard.views.payment_disputes` — no denormalized counters to keep in sync, no
risk of drifting from the underlying data.

## 5. Scalability — replacing manual verification with a real bank API later

The design deliberately separates three layers that a naive implementation would
tangle together:

1. **Evidence** — `payment_proof`/`payment_reference`/`payment_amount_claimed` on
   `Order`. A real bank API integration would want exactly this data to reconcile
   a claimed transfer against a real statement line — this isn't throwaway work.
2. **Decision** — whoever/whatever decides a transfer is genuine. Today that's a
   seller's click or an admin's dispute resolution. A future automated
   bank-statement matcher becomes a **third decider**, nothing more.
3. **Effect** — `_mark_bank_transfer_paid()`. Every decider, present and future,
   calls this same function. The order lifecycle, buyer UI, and seller UI never
   need to change when a new decider is added.

## 6. `Dispute` model changes

`Dispute.order` changed from `OneToOneField` to `ForeignKey` (`related_name=
'disputes'`) — a payment dispute happens before delivery, a damage/non-receipt
dispute happens after, and an order that survives one should still be able to have
the other later. `DisputeReason` gained `PAYMENT_NOT_RECEIVED` (seller-initiated
denial) and `PAYMENT_NO_RESPONSE` (system-initiated escalation); `DisputeResolution`
gained `PAYMENT_CONFIRMED`/`PAYMENT_REJECTED` (no refund/reshipment concept applies
before a payment has even been confirmed). `Order.has_active_dispute` gates
opening a *new* dispute so a resolved/closed one from earlier in the order's life
doesn't permanently block a later, unrelated one.

## 7. Auto-escalation

`python manage.py escalate_stale_payment_claims [--days=3]` — meant to run daily.
Finds `BANK_TRANSFER` orders sitting in `PAYMENT_REPORTED` past the response
window with no active dispute already, and escalates them straight to admin
review. This is what stops a seller from indefinitely stonewalling a buyer by
simply never clicking confirm *or* deny.
