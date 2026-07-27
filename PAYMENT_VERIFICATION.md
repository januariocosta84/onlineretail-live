# Bank-Transfer Payment Verification — Architecture & Fraud Prevention

**Purpose**: the manual "Bank Transfer" payment method (buyer pays
**TimorMart's own bank account**, the platform holds the funds and pays the
seller out later — see `BANK_SIMULATOR_ARCHITECTURE.md` for how this differs
from the platform-mediated *automated* gateway) previously had zero evidence
attached to it: "I've sent payment" was a bare button click with nothing to
back the claim. This document covers what replaced that: receipt capture,
fraud-signal flagging, and an admin dispute-resolution queue that is the
**only** way a bank-transfer order gets marked Paid.

> **2026-07-27 redesign**: bank transfer used to be a direct buyer→seller
> payment the platform never touched, and the seller themselves confirmed or
> denied receipt (see `HANDOFF.md` for that history). With legal clearance
> obtained, it was changed to the escrow-style flow described below: the
> buyer now pays the platform, and only an **admin** — who can actually see
> the platform's real bank statement — confirms a claim. A seller has no
> confirm/deny action left; `confirm_payment_received`,
> `deny_payment_received`, and the `escalate_stale_payment_claims` command
> (built for "a seller never responds," a scenario that's no longer
> possible) were all deleted, not just deprecated.

The failure mode this was built to close:
- **A buyer submits a fake/edited receipt** — nothing previously stopped a
  reused or doctored screenshot from being accepted as sufficient evidence.

---

## 1. How it fits together

```
Buyer clicks "I've sent payment" (mark_payment_sent)
        │  a real form (PaymentProofForm), not a bare click:
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
Order.status = PAYMENT_REPORTED
Dispute created immediately (reason=PAYMENT_CLAIM_SUBMITTED,
status=UNDER_REVIEW) — there is no seller step to wait through
        │
        ▼
Admin reviews at /dashboard/payment-disputes/ ("Bank transfer claims")
— sees the receipt, reference/amount, any auto-flag reason, and the
buyer's prior track record on this exact kind of claim, then checks the
platform's real bank statement for a matching transfer
        │
        ┌───────────────┴───────────────┐
        ▼                                ▼
    Approve                           Reject
    → _mark_bank_transfer_paid()      → Order.status = CANCELLED
    (credits SellerBalance, marks
    Paid, decrements stock, clears
    cart)
```

**Why the effect function matters**: `_mark_bank_transfer_paid()` in
`olretail/payment_views.py` is the single place that actually flips an order
to Paid, credits the seller's balance, decrements stock, and clears the
cart. It is called from exactly one place now — an admin's dispute
approval (`dashboard.views.payment_dispute_action`) — so there is only ever
one code path with those side effects.

---

## 2. Evidence captured (`Order` fields)

| Field | Purpose |
|---|---|
| `payment_proof` | The receipt/screenshot image itself |
| `payment_reference` | Buyer-entered bank transfer reference number |
| `payment_amount_claimed` | Buyer-entered amount sent (compared against `order.total`) |
| `payment_proof_hash` | SHA-256 of the uploaded image — powers duplicate detection |
| `payment_flagged` / `payment_flag_reason` | Set automatically when a signal fires; shown to admin |

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
which is out of scope here (see §5). The admin manually checking the
platform's real bank statement before approving is today's actual backstop
against this gap, not a signal computed here.

## 4. Trust signals on the admin dispute screen

Computed live from existing `Dispute` data, not a separate scoring system to
maintain:
- **Buyer's prior unverified claims** — times this buyer's payment claim was
  rejected as unverifiable (`DisputeResolution.PAYMENT_REJECTED`).

(A seller-side "prior wrongful denials" signal existed here before the
2026-07-27 redesign — it's gone because sellers no longer have a deny
action to be wrong about.)

This is a cheap `Dispute.objects.filter(...).count()` query computed per-row in
`dashboard.views.payment_disputes` — no denormalized counter to keep in sync, no
risk of drifting from the underlying data.

## 5. Scalability — replacing manual verification with a real bank API later

The design deliberately separates three layers that a naive implementation would
tangle together:

1. **Evidence** — `payment_proof`/`payment_reference`/`payment_amount_claimed` on
   `Order`. A real bank API integration would want exactly this data to reconcile
   a claimed transfer against a real statement line — this isn't throwaway work.
2. **Decision** — whoever/whatever decides a transfer is genuine. Today that's
   an admin's dispute resolution. A future automated bank-statement matcher
   becomes a **second decider**, nothing more.
3. **Effect** — `_mark_bank_transfer_paid()`. Every decider, present and future,
   calls this same function. The order lifecycle and buyer UI never need to
   change when a new decider is added.

## 6. `Dispute` model changes

`Dispute.order` is a `ForeignKey` (`related_name='disputes'`), not a
`OneToOneField` — a payment dispute happens before delivery, a
damage/non-receipt dispute happens after, and an order that survives one
should still be able to have the other later. `DisputeReason` includes
`PAYMENT_CLAIM_SUBMITTED` (the current, only bank-transfer-claim reason —
added 2026-07-27) alongside the historical `PAYMENT_NOT_RECEIVED`
(seller-denial) and `PAYMENT_NO_RESPONSE` (system-escalation) values, kept
so any pre-existing rows from before the redesign still display and filter
correctly; neither historical reason is created by new code anymore.
`DisputeResolution` has `PAYMENT_CONFIRMED`/`PAYMENT_REJECTED` (no
refund/reshipment concept applies before a payment has even been
confirmed). `Order.has_active_dispute` gates opening a *new* dispute so a
resolved/closed one from earlier in the order's life doesn't permanently
block a later, unrelated one.

## 7. Seller balance crediting (added 2026-07-27)

Since the platform now actually holds the money, `_mark_bank_transfer_paid()`
credits the seller exactly like Stripe's `_mark_payment_succeeded()` does:

```python
Transaction.objects.create(
    order=order, seller=order.seller, amount_cents=int(order.subtotal * 100),
    transaction_type=TransactionType.COMMISSION,
    description=f"Earnings from order {order.order_number}",
)
seller_balance, _created = SellerBalance.objects.get_or_create(seller=order.seller)
seller_balance.add_commission(int(order.subtotal * 100))
```

This "just works" because checkout (`_process_bank_transfer_checkout`) now
computes a real proportional `commission_amount` split (the same
cents-based algorithm Stripe/the bank simulator use), so `order.subtotal`
already excludes the platform's cut. The credited balance flows into the
*same* manual payout batch (`olretail/payouts.py`
`create_scheduled_payouts`) Stripe earnings already use — no new payout
mechanism was built for this.
