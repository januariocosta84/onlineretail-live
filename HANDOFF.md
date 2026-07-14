# HANDOFF — TimorMart

Last updated: 2026-07-14 (evening session — subscriptions, payment fix, branding)

## What this is

A Django marketplace for Timor-Leste, branded **TimorMart** (Django project
module is still named `TLoretail` internally — deliberately not renamed, see
Branding section). Sellers register, create product listings (which need
admin approval unless the seller is a paid subscriber — see Subscriptions),
and buyers browse, search, filter by category, leave comments, and buy via an
in-app cart/checkout flow — paying by **Stripe card** or **direct bank/mobile
transfer to the seller** (or arranging sales directly via the seller's phone
number/WhatsApp — all paths work). Four categories (Housing, Vehicles,
Motorcycles, Services) are contact-the-seller-only and never show a cart
button — see Cart-restricted categories. UI is bilingual: **English**
(default) and **Tetum** (`/tet/` URL prefix).

- Project root: `C:\Users\DACOSTAJA\OneDrive - Food and Agriculture Organization\Desktop\My App\onlineretail-live`
- **Is now a git repository** (this was not true as of the 2026-07-12 entry
  below — it has since been initialized, with commits and a GitHub remote:
  `origin` → `https://github.com/januariocosta84/onlineretail-live.git`).
  `git status` currently shows a very large uncommitted diff (~1780 files) —
  most of that is generated/vendor content (`__pycache__`, `media/`,
  `staticfiles/`) plus every change described in this document; nothing has
  been committed by Claude in any session — commit only when explicitly asked.
- **Working venv is `.venv/` in the project root** (not an external temp
  path — that was true for an earlier session/machine setup, no longer
  accurate). Run everything via `.venv\Scripts\python.exe manage.py ...`.

## State as of 2026-07-12

The app was fully modernized and verified in a single pass:

- **Django 3.1.4 → 5.2 LTS** (Django 3.1 cannot run on this machine's
  Python 3.13, and had known CVEs).
- All views/forms rewritten: validation, ownership checks, messages,
  pagination, sorting, working product edit/delete, working per-product
  comments, full password-reset flow, safe `next` redirects.
- Security: env-driven `SECRET_KEY`/`DEBUG`/hosts, HSTS + secure cookies when
  `DJANGO_SSL_REDIRECT=true`, strong-password enforcement on registration.
  `manage.py check --deploy` passes (one optional HSTS-preload notice).
- Templates overhauled (responsive, empty states, a11y); 20 dead template
  files deleted.
- Admin: product list columns/filters/search + bulk Approve/Unapprove actions.
- i18n: language code fixed from `tt` (= Tatar in Django → Cyrillic leaked
  into the UI) to `tet`. Complete Tetum catalog (172 strings, all translated).
- Seller contact (2026-07-13): product detail page shows the seller's phone as
  a `tel:` link plus a **Chat on WhatsApp** button (`wa.me` link with a
  pre-filled, translated message containing the product name and URL).
  `Seller.whatsapp_number` normalizes numbers to international format
  (adds Timor-Leste's 670 prefix when missing).
- Contact gating (2026-07-14): phone/WhatsApp on the detail page are only
  rendered for buyer-capable viewers (`can_view_contact` in `product_detail`:
  buyers, the listing's owner, and staff). Enforcement is server-side — the
  number never reaches the HTML otherwise. Guests see a lock card with Sign
  in (carrying `?next=` back to the product) / Sign up; seller-only accounts
  see an upgrade card with a one-click **Upgrade to Buyer & Seller** action
  (`accounts:upgrade_to_buyer`, POST, idempotent, staff refused).
- Sold-out management (2026-07-13): quantity 0 = sold out. Sellers can edit
  sold-out products (old form rejected qty < 1), and the dashboard has a
  one-click "Mark as sold out" action (`olretail:mark_sold`, POST,
  owner-scoped). Sold-out listings stay visible with an "Out of stock" /
  "Esgotadu" badge and are excluded from the dashboard inventory value.
- DB migrations `0002` (slug dedupe + field fixes) and `0003` (title_tt →
  title_tet) are **applied** to `db.sqlite3`. `makemigrations --check` is clean.
- Everything verified in the browser: register → create/edit/delete product →
  admin approve → public visibility, comments, search, sorting, category
  filter, login/logout, weak-password rejection, 404s, Tetum/English
  round-trip, mobile layout. No console or server errors.

## How to run locally

**Current setup (2026-07-14 evening): venv lives at `.venv/` in the project
root**, inside OneDrive — contradicts the advice below (which was written
when the venv lived outside OneDrive on a different machine/session). It
works fine as-is; if OneDrive sync issues crop up, recreate it outside
OneDrive per the original advice kept below for reference.

```powershell
cd "C:\Users\DACOSTAJA\OneDrive - Food and Agriculture Organization\Desktop\My App\onlineretail-live"
$env:DJANGO_DEBUG = "true"
.venv\Scripts\python.exe manage.py runserver
```

If `manage.py` commands fail with `ModuleNotFoundError: No module named
'modeltranslation'` (or `stripe`, etc.), you're invoking the wrong Python —
use `.venv\Scripts\python.exe`, not a bare `python`/global interpreter; more
than one Python install exists on this machine and only `.venv` has the
project's dependencies.

<details><summary>Original advice (external venv, may be stale)</summary>

The working venv (already set up) is **outside OneDrive** on purpose:

```powershell
C:\Users\DACOSTAJA\AppData\Local\Temp\venv-olretail\Scripts\python.exe manage.py runserver
```

That venv lives in `%TEMP%` and may get wiped. To recreate anywhere (keep it
out of OneDrive — sync corrupts venvs and SQLite locks):

```powershell
python -m venv C:\dev\venv-olretail
C:\dev\venv-olretail\Scripts\pip install -r requirements.txt polib
```

There is also a Claude Code launch config named **`onlineretail`** (port 8033)
in the food-delivery-platform project's `.claude/launch.json`.
</details>

**GNU gettext is still not installed** on this machine — `compilemessages`
and `makemessages` fail (`Can't find msgfmt`). Use `compile_translations.py`
(polib-based, see bottom of this doc) to compile `.po` → `.mo` after editing
translations by hand.

## Accounts (state on 2026-07-14 evening)

| Username | Role | Password | Notes |
|---|---|---|---|
| `jcosta` | Superuser + Seller | `C0001395` | admin at `/admin/` and `/dashboard/` |
| `jnrdacosta` | Seller | **unknown — reset needed** | password was overwritten during payments testing on 2026-07-14 (original was never documented); use Django admin's "change password" or the password-reset flow before logging in as this user |
| `jnrdacosta_costa` | **Buyer & Seller** | `C0001395` | upgraded via `assign_role`; owns "Samsung Galaxy 23"; real orders (see below) |
| `jmoniz` | Buyer & Seller | unknown | genuine user account that appeared during payment testing, not created by Claude — see note below |
| `test_1` .. `test_90` | Seller | `C0001395` | **demo/QA data**, not real users — see Demo/seed data section |
| `test_91` .. `test_100` | Buyer | `C0001395` | same |

Users self-register at `/accounts/register/` choosing an account type.

**Demo data is now persistent by design** (unlike earlier sessions where QA
accounts were deleted after verification) — the 100 `test_*` accounts and
their ~800+ products/orders exist so the app has realistic browseable/
searchable/filterable content and are meant to be kept. Regenerate anytime
with `python manage.py seed_demo_users --reset` (see Demo/seed data section);
this is safe and does **not** touch non-`test_*` accounts or their data.

**Real (non-test) account activity found during sessions — left untouched:**
- `jnrdacosta_costa` attempted to buy `jnrdacosta`'s "Samsung Galaxy 23"
  listing (slug `samsung-galaxy-23-2`) via Stripe on 2026-07-14; stuck at
  "Pending Payment" (`ORD-20260714-001`) because Stripe test keys weren't
  configured. Once real keys are set, either complete that payment or cancel
  the order manually.
- A `jmoniz` account exercised real checkout flows too, including at least
  one completed bank-transfer purchase (orders `ORD-20260714-002/003`).

These are local dev credentials — rotate them before any real deployment.

## Roles (added 2026-07-13, Courier added 2026-07-14)

Self-registration offers three account types: **Buyer**, **Seller**, **Buyer & Seller**.
Roles = Django Groups (`Buyer`, `Seller`, `Courier`) + profile models
(`olretail.Buyer` / `olretail.Seller` / `olretail.Courier`). The single
source of truth is `accounts/roles.py` (`ROLE_DEFINITIONS`, `assign_role`,
`is_buyer`, `is_seller`, `is_courier`) — add new roles there only.
Menus/dashboards adapt via the `olretail.context_processors.roles` context
processor (`is_buyer` / `is_seller` / `is_courier` template vars).

- Buyers: browse, contact sellers (WhatsApp/call), post comments; no seller area.
- Sellers: full listing management; **cannot** post comments (enforced
  server-side in `product_detail`, not just hidden in the template).
- Buyer & Seller: both, one account. Login lands sellers on `/seller/`,
  buyer-only accounts on the store.
- **Courier**: not in the self-registration list — an admin grants it from
  `/dashboard/users/` to an existing account. Sees `/courier/deliveries/`
  (orders assigned to them) and can mark an assigned order Delivered with a
  required photo. See "Courier role + delivery photo proof" under Payments.
- Anonymous visitors can no longer comment (was open to everyone before);
  they see a sign-in prompt instead.
- **Staff accounts cannot buy, sell, or courier** (2026-07-13, extended
  2026-07-14): `is_buyer`/`is_seller`/`is_courier` return False for
  `is_staff` users, seller/courier pages redirect staff to `/dashboard/`,
  comment form is withheld, and the dashboard refuses to grant buyer/seller/
  courier roles to staff. Staff logins land on `/dashboard/`. jcosta's
  legacy listings stay published and are managed via the admin dashboard.
- `jnrdacosta` is seller-only; `jnrdacosta_costa` is buyer & seller.

## Admin dashboard (added 2026-07-13)

Staff-only dashboard at **`/dashboard/`** (link appears in the header for
`is_staff` users), separate from buyer/seller pages. New app: `dashboard/`.

- **Overview**: user/product/comment stat cards, 6-month bar charts
  (listings, registrations), top sellers, category distribution, recent
  admin activity, awaiting-review shortlist.
- **Approval workflow**: `Product.status` replaced the old `approved` boolean
  (pending / approved / changes requested / rejected / suspended — see
  `ProductStatus` in `olretail/models.py`; a read-only `approved` property
  keeps old template checks working). Queue at `/dashboard/queue/` with bulk
  approve/reject; per-product review page shows all details/images/seller and
  offers Approve / Request changes / Reject / Suspend / Restore. Reject and
  request-changes REQUIRE a reason, stored in `Product.moderation_note` and
  shown to the seller (dashboard table + listing banner). A seller editing a
  rejected/changes-requested product resubmits it to pending automatically.
- **Featured products**: star toggle; featured items headline the homepage
  carousel (only ones with a main image).
- **Products page**: search + status/category/seller filters, CSV export,
  permanent delete (confirm dialog).
- **Users page**: search/role filter, suspend/reactivate (guards: cannot
  modify self; only superusers modify superusers), grant buyer/seller role,
  password-reset link into Django admin, CSV export.
- **Comments page**: hide/show (`Comment.is_public`) and delete; hidden
  comments disappear from the storefront.
- **Audit log**: `dashboard.AuditLog` records every dashboard action with
  admin, action, target, detail, IP, timestamp (read-only in Django admin).
  View at `/dashboard/audit/`.
- Dashboard UI is English-only by design; seller-facing status strings are
  translated (catalog now 179 entries).

## Responsive / accessibility pass (2026-07-13)

Global styles live in `templates/shared/base.html` (and dashboard-specific
ones in `dashboard/templates/dashboard/base.html`):

- Skip-to-content link, visible `:focus-visible` outlines, and
  `prefers-reduced-motion` support.
- Touch ergonomics on coarse pointers (≥40px small buttons, taller
  nav/dropdown/pagination hit areas).
- Small-screen tuning: product-card images 150px, carousel capped at 220px,
  smaller headings, tightened header padding; `overflow-wrap` guards against
  long-word overflow; tables scroll inside `.table-responsive`.
- Admin dashboard sidebar collapses to a horizontal scrollable nav below 992px.
- Font/icon CDNs get `preconnect`; catalog/gallery images use `loading="lazy"`
  (carousel/detail hero stay eager for LCP).
- Filter inputs and icon-only buttons carry `aria-label`s; footer social
  placeholders are labelled (update hrefs when accounts exist).

## Product image gallery (2026-07-13)

The detail page has an interactive gallery (all markup/CSS/JS lives in
`templates/olretail/details.html`, vanilla JS, no new dependencies): large
main image (aspect-ratio preserved via object-fit: contain), clickable
thumbnails with an accent highlight, fade transitions, prev/next arrows with
wrap-around, touch swipe, adjacent-image preloading, and a full-screen
lightbox (click main image) with zoom toggle, arrow-key/Escape keyboard
control, focus management, and a position counter. Image URLs are passed
from `product_detail` as `gallery_urls` via `json_script`.

## Sentiment analysis (2026-07-14)

Comments are auto-scored on save by `olretail/sentiment.py` — a dependency-free
trilingual (Tetum / Portuguese / English) lexicon analyzer with consumed-
negation handling ("la diak" → negative) and emoji support. Fields:
`Comment.sentiment` (positive/neutral/negative, indexed) and
`sentiment_score` (migration 0005 backfilled existing rows).

- Product page: smile/frown icon per comment + positive/negative counts in
  the Comments heading (translated).
- Admin dashboard: "Comment sentiment" overview card with a
  "review negative" quick link; Comments page has a Negative filter tab and
  a Sentiment column. Django admin lists/filters by sentiment too.
- After extending the lexicon, re-score everything with
  `python manage.py analyze_comments`.
- Limits: lexicon-based (no sarcasm/context understanding); treat it as a
  moderation aid, not ground truth. Swap `analyze()` for an ML model later
  without touching callers.

## Payments (Stripe) — added 2026-07-14

Cart → checkout → Stripe PaymentIntent → webhook → order/commission/payout
tracking, plus buyer disputes. Models/views/forms were scaffolded in an
earlier session (`olretail/payment_models.py`, `payment_views.py`,
`payment_forms.py`, `PAYMENT_SYSTEM_ARCHITECTURE.md`) but weren't wired up or
reachable from the UI; this pass made it actually run:

- `payment_models.py` classes (`Cart`, `Order`, `Payment`, `Transaction`,
  `SellerBalance`, `Payout`, `Dispute`) are re-exported from `olretail/models.py`
  so Django's app registry/`makemigrations` picks them up — migrations
  `0006`/`0007` create them and are applied to `db.sqlite3`.
- `stripe` is installed in the working venv (was missing).
- Fixed a template bug (`checkout.html`/`seller_balance.html` used a
  nonexistent `|mul` filter — arithmetic now happens in the views instead).
- Fixed `DisputeForm.reason`: was a `<Select>` with zero options (plain
  `CharField`, uncompletable); added a `DisputeReason` choice set.
- Wrote the 3 templates that didn't exist yet: `open_dispute.html`,
  `dispute_detail.html`, `seller_respond_dispute.html`; wired the
  seller-response form into the `dispute_detail` view.
- UI entry points added: **Add to Cart** button on the product detail page
  (gated to buyer-capable, non-owner, in-stock, approved products via
  `can_add_to_cart` in `product_detail`), and Cart/My Orders (buyers),
  Orders/Earnings (sellers) links in the header nav.
- Verified end-to-end with the Django test client: login → product page →
  add to cart → checkout (fee breakdown renders) → Stripe call fails cleanly
  on the demo key (expected — see below) → order/dispute detail, seller
  response, seller orders, seller balance, buyer orders all render clean.

**Still needed before this is really usable:**
- Real Stripe **test** keys. `STRIPE_PUBLIC_KEY`/`STRIPE_SECRET_KEY`/
  `STRIPE_WEBHOOK_SECRET` in `TLoretail/settings.py` currently fall back to
  `sk_test_demo` etc. — checkout POSTs to Stripe and fails with
  `Invalid API Key provided`, caught and shown as a friendly error. Get real
  ones from a Stripe account (dashboard.stripe.com, test mode) and set them
  as env vars.
- Webhook endpoint is `/webhook/stripe/`; for local testing use
  `stripe listen --forward-to localhost:8033/webhook/stripe/` once keys are set.
- ~~`_process_checkout` only creates a `Payment` for the *first* order in a
  multi-seller cart~~ — **fixed 2026-07-14 evening, see "Multi-seller Stripe
  checkout fix" below.**

### Payment confirmation reconciliation (added 2026-07-14)

The Stripe checkout page confirms the card with Stripe directly from the
browser (`stripe.confirmCardPayment` in `payment.html`) and only *redirects*
to the confirmation page — it never tells Django the payment succeeded. The
only thing that used to flip `Order.status` to Paid was the `/webhook/stripe/`
endpoint, which Stripe can't reach on `localhost` without a tunnel (see
below), so orders got stuck on "Pending Payment" even after a successful
charge.

Fix: `payment_confirmation` now calls `_reconcile_payment(order)` when the
order is still pending — it asks Stripe directly for the PaymentIntent's
real status and, if `succeeded`, applies the same effects the webhook would
have. The shared logic (mark paid, record commission, credit seller balance,
decrement stock, clear cart) was pulled into one `_mark_order_paid()` helper
used by both the webhook and the reconciliation path — both are idempotent
(tested calling each twice; no double commission, no double stock
decrement). The webhook is still the primary path; reconciliation is the
safety net for local dev and any missed/delayed webhook delivery.

For local testing, set up the Stripe CLI tunnel so the webhook actually
fires: `stripe listen --forward-to localhost:8033/webhook/stripe/`, then set
the printed `whsec_...` as `STRIPE_WEBHOOK_SECRET`.

### Bank / mobile transfer — direct buyer → seller payment (added 2026-07-14)

Timor-Leste has working mobile/bank transfers, so checkout now offers a
second payment method alongside Stripe: the buyer sends money **directly to
the seller's bank/mobile account**, bypassing the platform entirely. This
was a deliberate choice over Stripe Connect — see the "Seller payouts"
section below for the reasoning (the platform never holding this money
sidesteps the same money-transmitter licensing question).

- `Order.payment_method` (`stripe` / `bank_transfer`) and a new
  `OrderStatus.PAYMENT_REPORTED` state (buyer says they paid, awaiting
  seller confirmation) — migration `0008`.
- **No commission is taken on bank-transfer orders** — `commission_amount`/
  `payment_fee` are `0`, `total` = `subtotal`. The platform never touches
  this money, so there's nothing to take a cut of (deliberate simplicity;
  revisit only if this payment method needs to fund the platform somehow —
  e.g. a seller subscription fee — later).
- Sellers set free-text bank/mobile money details on
  `Seller.payment_instructions` via the self-service page at
  `/seller/payment-settings/` (staff accounts are blocked from this, same as
  every other seller-only page — see Roles section). If blank, bank transfer
  is refused at checkout for that seller's items with a message telling the
  buyer to pick Card instead.
- Flow: checkout → `bank_transfer_instructions.html` (shows each seller's
  details + a reference code = the order number) → buyer clicks **"I've
  sent payment"** (`mark_payment_sent`, status → Payment Reported) → seller
  sees it on `/seller/orders/` (quick "Confirm Payment" button) or the order
  detail page and clicks **"Confirm payment received"**
  (`confirm_payment_received`) → order → Paid, stock decremented, cart
  cleared. Confirmation is **seller-gated on purpose** — a buyer alone
  can't move an order to Paid, to prevent false claims.
- Since there's no Stripe involved, `_mark_bank_transfer_paid()` is a
  separate, simpler helper from the Stripe path's `_mark_order_paid()` — no
  `Payment` row, no `Transaction`/commission, no `SellerBalance` change.
- Verified end-to-end with the test client: missing-instructions guard at
  checkout, instructions save, order creation with $0 commission, buyer
  mark-sent, seller confirm-received, stock/cart/status all correct.

### Delivery tracking (added 2026-07-14)

Previously `seller_update_order_status` (mark shipped/delivered) existed in
`payment_views.py` but **no template linked to it** — there was no UI path
to ship an order at all. Now live on the order detail page:

- `Order.courier_name` / `tracking_number` / `shipped_at` (migration `0009`)
  — seller enters courier + tracking number when marking an order Shipped
  (`ShipOrderForm`); both are optional free-text (no courier API/lookup).
- `DeliveryUpdate` model — free-text timestamped notes the seller can post
  while an order is Shipped (e.g. "Left Dili warehouse, arriving Baucau
  tomorrow"), shown to the buyer as a timeline on the order page. Manual, by
  design — no delivery service integration exists to automate this.
- Status transitions are guarded: Shipped only from Paid, Delivered only
  from Shipped (previously any status could jump to either, silently).
- Buyer sees courier/tracking info + the update timeline, read-only. Only
  the seller can post timeline updates or advance Pending→Shipped.
- Verified end-to-end (disposable throwaway test accounts, not the real
  dev accounts, to avoid touching real order data — see note below): ship
  with courier info → post update → buyer sees both → mark delivered →
  guard rejects shipping an already-delivered order.

### Courier role + delivery photo proof (added 2026-07-14)

Delivery previously had no independent confirmation — only the seller could
mark an order Delivered, with no evidence. Now:

- New **Courier** role (`olretail/models.py` `Courier` profile,
  `accounts/roles.py` `ROLE_COURIER`/`is_courier`) — same groups+profile
  pattern as Buyer/Seller, but **not self-registerable**: an admin grants it
  from `/dashboard/users/` (a "+Courier" button, same mechanism as granting
  Buyer/Seller). Reasoning: it carries the ability to confirm deliveries, so
  it shouldn't be something anyone can pick at signup. Staff are excluded,
  same as every other role.
- `Order.assigned_courier` (FK to `Courier`, nullable) — when a seller marks
  an order Shipped, they optionally pick a registered courier from a
  dropdown (`ShipOrderForm.assigned_courier`) in addition to the existing
  free-text `courier_name`. Leaving it unset means self-delivery — the
  seller keeps the ability to mark their own orders delivered.
- **Delivering now requires a photo.** `Order.delivery_photo` (ImageField,
  `migration 0010`) — `mark_delivered` (new view, replaces the old
  no-evidence "delivered" branch of `seller_update_order_status`) requires
  `DeliveryProofForm.photo`; rejected without one. Usable by either the
  owning seller (self-delivery) or the specifically assigned courier — no
  one else. The file input sets `capture="environment"` so mobile browsers
  open the camera directly.
- `/courier/deliveries/` — a courier's own dashboard: orders assigned to
  them that are pending delivery, and a short history of ones they've
  completed. Each links to the order detail page, where the actual
  "mark delivered + upload photo" form lives.
- Buyer and seller both see the delivery photo (as an image, click to view
  full-size) on the order page once delivered, plus the assigned courier's
  name and mobile number if one was set.
- Verified end-to-end: admin grants courier role → seller ships and assigns
  that courier → an *unrelated* courier account is correctly blocked from
  viewing the order → the assigned courier sees it on their dashboard →
  marking delivered without a photo is rejected → with a photo it succeeds
  → buyer sees the courier's name and the photo → self-delivery path
  (no courier assigned) still works for the seller → guards reject
  delivering before shipping and re-shipping an already-delivered order.
- `Order` is now registered in Django admin (`OrderAdmin` — it wasn't
  before, so staff had no way to view/manage orders outside the dashboard,
  which has no orders section). Also doubles as the fix for reassigning a
  courier to an order that's already Shipped — the seller-facing "Mark as
  Shipped" form only offers the courier picker at the Paid→Shipped
  transition (see gap list), so `/admin/olretail/order/<id>/change/` →
  `Assigned courier` is the only way to (re)assign one afterward.
- **Pitfall found live:** granting the Courier role by checking the
  "Courier" group directly on a user's Django admin page (rather than the
  dashboard's "+Courier" button) adds the group but **not** the `Courier`
  profile row — and `is_courier()` checks `hasattr(user, "courier")`
  (the profile), not group membership, so the account silently doesn't get
  courier access with no error anywhere. Always grant via
  `/dashboard/users/` → "+Courier", which calls `assign_role()` and creates
  both. If this happens again: `Courier.objects.get_or_create(user=<user>)`
  in a shell fixes it immediately.

**A note on real data found during this work:** while testing payments this
session, several genuine (non-test) orders showed up that weren't created by
Claude — `jnrdacosta_costa` and a `jmoniz` account exercising real checkout
flows, including one completed bank-transfer purchase. These were left
untouched; if you see orders you don't recognize creating, that's why.

### Seller payouts — by design, still manual (added 2026-07-14)

The platform charges the buyer in full into its own Stripe account (no
Stripe Connect) — sellers accrue an `available_balance` on `SellerBalance`,
they don't receive money automatically. That's an intentional decision, not
a bug: acting as the money-holding intermediary and auto-transferring to
sellers (via Stripe Connect) would likely trigger money-transmitter/e-money
licensing questions worth resolving separately before automating it.

What exists now to make the manual process trackable instead of ad hoc:

- `olretail/payouts.py` (`create_scheduled_payouts()`) finds every seller
  whose `available_balance` has cleared their `min_payout_cents` threshold
  (default $500) and creates a `Payout` row per seller, moving that amount
  from available → pending. Callable two ways:
  - `python manage.py schedule_payouts` (run by hand, or wire into a cron
    scheduler later — nothing currently runs it automatically)
  - the **"Run payout batch"** button on `/dashboard/payouts/` (staff only)
- Each `Payout` has a detail page (`/dashboard/payouts/<id>/`) where an
  admin fills in bank transfer details (bank name/account number/holder/
  notes — these aren't collected from sellers anywhere yet, admin enters
  them by hand) and, **after actually sending the transfer themselves**,
  marks it Processing / Paid / Failed. Paid moves the amount to
  `total_payouts`; Failed returns it to `available_balance`
  (`SellerBalance.fail_payout`).
- Every payout action is audit-logged (`dashboard.AuditLog`), same as the
  rest of the dashboard.
- Sellers see their own payout history (read-only) on `/seller/balance/`.

Nothing here moves real money — it's a ledger + admin workflow so payouts
don't get tracked in someone's head or a spreadsheet.

## Branding — "TimorMart" (added 2026-07-14 evening)

The storefront name changed from **"Timor Online Retail"** to **"TimorMart"**
everywhere user-facing: page titles, header logo/alt text, footer, emails,
WhatsApp share text, Django admin header, and all docs (this file included).
Deliberately **not** renamed: the Django project module `TLoretail/` (folder
name, `settings.py` module path, `manage.py`, deployment config) — renaming
that is a much riskier change touching every import and the deployment
pipeline for no user-visible benefit. If a full rename is ever wanted, do it
as its own isolated change with a deploy dry-run.

- Header logo: `static/mdb/img/logo.jpg` (swapped a couple of times this
  session — earlier candidates `logocompanha.png`/`Timonret.jpg` are still on
  disk but unused; safe to delete). Whichever logo file is live, if it looks
  tiny at its set `height`, check whether the source image has large
  white-space padding — cropping the source (Pillow, `ImageChops.difference`
  against a white background to get a bounding box) fixes it much better
  than just bumping the `height` attribute, which only enlarges the padding.
- Favicon: `static/mdb/img/favicon.ico` (multi-resolution, 16–256px),
  generated from the logo's cart icon on a solid red rounded-square backdrop
  — a bare cart-on-white icon is invisible at browser-tab size, needs
  contrast. Wired up in `templates/shared/base.html`.
- After changing any file under `static/`, run `collectstatic` and **restart
  the dev server** — WhiteNoise (`WHITENOISE_USE_FINDERS`) builds its file
  list once at process startup, so a running server won't see new static
  files even after `collectstatic` completes until it's restarted.

## Demo/seed data (added 2026-07-14 evening)

`python manage.py seed_demo_users [--reset]` (`olretail/management/commands/
seed_demo_users.py`) creates 100 realistic demo accounts for testing every
buyer/seller/admin feature without hand-crafting data:

- **90 sellers** (`test_1`–`test_90`) each list exactly 1 product per
  category (9 categories × 90 = 810 products), realistic names/prices/
  quantities per category, ~85% auto-approved / rest spread across pending /
  changes-requested / suspended so the moderation queue has real cases.
  Category-colored placeholder JPEGs stand in for product photos.
- **10 buyers** (`test_91`–`test_100`) each get a few cart items and several
  historical orders spanning every `OrderStatus` and both payment methods,
  with matching `Payment`/`Transaction`/`SellerBalance` records.
- `--reset` cleanly wipes only `test_*` data (Transactions → Payments →
  Orders → Products → Carts → SellerBalances → Users, in FK-safe order) —
  verified it never touches non-`test_*` accounts/orders.
- All passwords: `C0001395`.

## Multi-seller Stripe checkout fix (added 2026-07-14 evening) — was a real bug

**Found while answering "if a buyer buys from different sellers, how does
payment work?"** — traced the code and confirmed: when a cart spanned
multiple sellers and the buyer paid by **Stripe**, only the *first* seller's
order ever got marked Paid. `Payment` was `OneToOneField` to a single
"primary" order; the webhook/reconciliation only ever touched that one
order. Every other seller in the same checkout had no `Payment` row at all,
so their order sat at "Pending Payment" forever — stock never decremented,
seller never credited — even though the buyer had already been charged for
it as part of the combined PaymentIntent total. Bank-transfer checkouts were
never affected (each order confirmed independently by its own seller).

Fixed properly, not patched:

- `Order.payment` is now a nullable `ForeignKey` to `Payment` (was the
  reverse of a `Payment.order` OneToOneField, which is now removed) — one
  `Payment` (one Stripe charge) can now correctly have many sibling `Order`s.
  Migration `0011` is a 4-step migration (add field → **data migration
  copying existing links** → remove old index → remove old field) — verified
  it preserved both real pre-existing orders' payment links with zero data
  loss before applying.
- Commission **and** Stripe's processing fee are now split proportionally
  across each seller's order by their share of the cart subtotal (previously
  the *full* combined fee was stamped onto every order — a second latent
  bug: summing all orders' totals overcounted the fee N times for N sellers).
  Remainder cents land on the last item so per-order totals sum back exactly
  to what Stripe actually charges.
- `_mark_order_paid(order, ...)` → `_mark_payment_succeeded(payment, ...)`:
  now iterates every order sharing that `Payment` and applies the paid
  side-effects (status, stock, commission `Transaction`, `SellerBalance`
  credit, cart clear) to each, inside one atomic transaction.
- `payment_confirmation`'s "related orders" display used to be a fragile
  "orders created within ±1 minute" time-window heuristic — replaced with an
  exact query via the shared `Payment`.
- Verified live end-to-end (Django test client, Stripe API call stubbed):
  a real 3-seller cart checkout created one `Payment` for 3 orders across 3
  different sellers, totals reconciled exactly, and firing the webhook
  correctly marked all 3 paid — stock decremented and balances credited for
  all three, not just the first.

## Seller subscriptions / listing limits (added 2026-07-14 evening)

Free sellers are capped at **10 product listings**; posting more requires a
paid plan — **$11/month or $100/year, admin-confirmed** (no automated
billing — same bank-transfer-and-report pattern as everywhere else in this
app). New file `olretail/subscription_models.py`, migration `0012`.

- `SellerSubscription` (one row per seller): current `plan`
  (free/monthly/yearly) + `expires_at`. `can_post_product()` = has an active
  paid plan OR fewer than 10 total listings (counts *all* statuses — pending/
  rejected/suspended listings still used a "slot", not just approved ones —
  flag if that's not the intended interpretation).
- `SubscriptionRequest`: seller picks a plan and reports how/when they paid
  (bank/mobile transfer to the platform — instructions configurable via
  `PLATFORM_PAYMENT_INSTRUCTIONS` in settings) → `pending`. Only one pending
  request per seller at a time. Admin reviews at `/dashboard/subscriptions/`,
  **Approve** (activates the plan — extends from current expiry if already
  active, not from "now", so renewing early doesn't lose paid time) or
  **Reject** (reason required, kept on record, seller stays blocked).
- **Enforcement:** `product_create` redirects to `/seller/subscription/`
  instead of showing the form at all once the limit is hit.
- **Subscribers skip the approval queue** — their new listings save straight
  to `approved` instead of `pending` (added when explicitly requested after
  the limit feature). Deliberately scoped to *new* listings only:
  `product_update`'s existing behavior (editing a `rejected`/
  `changes_requested` listing resubmits to `pending`) is untouched even for
  subscribers — an admin's specific content rejection isn't something a
  subscription should let a seller bypass.
- **On expiry: listings are retained, only new posts are blocked** (explicit
  product decision, not an oversight) — nothing auto-hides or suspends a
  seller's existing catalog when their plan lapses; hiding inventory
  overnight risks buyers with in-flight orders and feels punitive. Two
  banners on `/seller/subscription/` and `/seller/` (My products) instead:
  an amber "expires in N days" nudge once a subscriber is both within 5 days
  of expiry *and* over the free limit, and a red "expired — listings stay
  live, but you can't add new ones" banner once it actually lapses.
- Seller UI: `/seller/subscription/` (plan picker, payment instructions,
  status/usage banner, request history), usage banner + "Manage
  subscription" link on `/seller/` (My products), "Subscription" link in the
  header seller nav.
- Admin UI: `/dashboard/subscriptions/` (list + status filter) and detail
  page (approve/reject) — same list/detail/audit-logged pattern as Payouts.
- Verified end-to-end (Django test client) for every path: hit-the-limit
  redirect, submit request, blocked from double-submitting while pending,
  admin approve → immediately unblocks posting → new listing auto-published,
  admin reject → seller stays blocked → can resubmit, and all three renewal
  banner states (expiring-soon / expired-over-limit / normal).
- **Known gap:** the new user-facing strings in this feature
  (`{% trans %}`/`{% blocktrans %}` in `seller_subscription.html`,
  `lista.html`, `product_form.html`, and the new success/warning messages in
  `views.py`/`payment_views.py`) are **not yet in the Tetum `.po` catalog** —
  they'll render in English even on `/tet/` pages until someone adds them by
  hand (gettext isn't installed to auto-extract via `makemessages`, see
  Translations section).

## Cart-restricted categories (added 2026-07-14 evening)

**Housing, Vehicles, Motorcycles, and Services** never show an "Add to Cart"
button — these are big-ticket or service listings meant to be arranged
directly with the seller (viewings, financing, scheduling — all off-
platform), not bought through checkout.

- `Product.cart_purchasable` property (`olretail/models.py`) checks
  `category.slug` against `NON_CART_CATEGORY_SLUGS` — **matched by slug, not
  title**, since `Category.title` is translated (Tetum) and a literal string
  match would silently break in `/tet/`.
- Enforced in three places, not just template hiding: `product_detail`'s
  `can_add_to_cart` flag (detail page shows a "contact the seller directly"
  note instead), `add_to_cart` (rejects a direct POST bypass with an error
  message), and `checkout` (rejects proceeding if a stale/legacy cart row
  somehow still holds a restricted item).
- Cleaned up 14 pre-existing cart rows from the demo-seed data that violated
  this rule (seeding predates the rule and picked random categories).
- Verified live for all four restricted categories + a control category
  (Electronics, unaffected) — button hidden, note shown, direct POST to
  `/cart/add/<id>/` correctly rejected server-side.

## Key workflows

- **Listing approval:** new products start as `pending` and are invisible
  to buyers. Approve in `/dashboard/queue/` (preferred) or via the Django
  admin bulk action.
- **Password reset:** works end-to-end; emails print to the server console
  unless SMTP env vars are set (see README table).

## Translations (English / Tetum)

- English is the source language (msgids). Tetum lives in
  `locale/tet/LC_MESSAGES/django.po` — **all strings translated**, including
  overrides for Django built-ins (password rules, "This field is required.",
  lowercase model labels like `username`).
- Category names are translated per-row in the DB (`title_en` / `title_tet`
  columns, managed by django-modeltranslation; edit them in the admin).
- After editing any `.po`: `python compile_translations.py` (uses polib; GNU
  gettext is NOT installed on this machine so `compilemessages` won't work),
  then restart the server. `makemessages` also needs gettext — if you add new
  `{% trans %}` strings, add them to the `.po` by hand or install gettext.
- Product condition values are stored in English ("New"/"Second Hand") and
  translated only for display — don't translate the stored values.
- **Not yet translated:** all the Subscriptions feature's user-facing
  strings (added 2026-07-14 evening, see Seller subscriptions section) —
  they fall back to English on `/tet/` pages until added to the `.po` by
  hand (no gettext on this machine to auto-extract them).

## Deployment notes

- `Procfile` (gunicorn) + `runtime.txt` (python-3.13.5) target Heroku; the old
  `onlineretails2021.herokuapp.com` deployment is long dead. Before deploying:
  set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`,
  `DJANGO_SSL_REDIRECT=true`; run `collectstatic` (WhiteNoise serves static).
- **Media is on local disk** (`media/`) and served by Django — fine for one
  small server, ephemeral on Heroku. Move to S3-compatible storage before real use.
- SQLite is fine at this scale; switch to Postgres via `DATABASES` if needed
  (psycopg/dj-database-url are commented in requirements.txt).

## Known gaps / next steps

1. Payments need real Stripe test keys to actually process a charge (see
   Payments section above) — code path is wired but untested against Stripe.
2. No email verification on registration.
3. No automated tests — all verification was manual in-browser / test client.
4. ~~Not under version control~~ — now a git repo with a GitHub remote (see
   top of doc); nothing has been committed yet in any Claude session.
5. Old `/tt/...` bookmarks 404 (language code renamed to `/tet/`).
6. Tetum shows `$ 16000.00` without thousands separators (locale has no
   number format; enable `USE_THOUSAND_SEPARATOR` if wanted).
7. `locale/pt-pt/` is a stale near-empty catalog — delete or complete it.
8. Payouts still require a human to run the batch, send the actual bank
   transfer, and mark it paid. ~~No multi-seller-cart checkout support for
   the Stripe path~~ — **fixed 2026-07-14 evening**, see "Multi-seller
   Stripe checkout fix" section.
9. `jnrdacosta`'s password is unknown — overwritten during testing on
   2026-07-14 (see Accounts table); reset it before using that account.
10. Bank-transfer confirmation is trust-based beyond the seller's word — no
    proof-of-transfer upload, no admin arbitration if a seller wrongly
    claims non-receipt. Fine for low volume with known sellers; revisit if
    disputes come up (the existing `Dispute` model already covers this
    payment method — a buyer can open one on a paid bank-transfer order
    same as any other). **Subscription payments (added 2026-07-14 evening)
    have the exact same trust model** — no proof-of-transfer upload, admin
    approves on their word that the platform account was paid.
11. Delivery tracking is manual (courier name/tracking number/status notes
    typed by the seller, delivery photo taken by whoever delivers) — no
    courier API integration, no buyer-facing map, no automated "out for
    delivery" notifications, no way for a courier to reject an order once
    assigned. Reassigning a courier after Shipped isn't possible from the
    seller-facing UI (that form only appears at Paid→Shipped) — use
    `/admin/olretail/order/<id>/change/` → `Assigned courier` instead
    (Order is now registered in Django admin).
12. No admin UI to manage courier accounts beyond the dashboard's "+Courier"
    grant button — no list of couriers, no way to revoke the role short of
    removing them from the `Courier` Django group/deleting the profile via
    admin.
13. Subscription plan prices/durations ($11/mo, $100/yr, 30/365 days) are
    hardcoded in `olretail/subscription_models.py` (`PLAN_PRICES`,
    `PLAN_DURATION_DAYS`) — fine for now, move to DB-configurable if pricing
    needs to change without a deploy.
14. No email/SMS notification when a subscription is expiring or a
    subscription/payout request is approved/rejected — seller only finds out
    by visiting the relevant page (banners are in-app only).
15. New Subscriptions feature strings aren't in the Tetum `.po` catalog yet
    (see Translations section).

## File map (the parts that matter)

- `TLoretail/settings.py` — env-driven config, security, i18n, logging,
  Stripe/commission settings (`STRIPE_*`, `COMMISSION_RATE`,
  `PLATFORM_PAYMENT_INSTRUCTIONS` for subscription payments)
- `olretail/` — catalog app: models (incl. `Courier`, `NON_CART_CATEGORY_SLUGS`/
  `Product.cart_purchasable`), views, forms, urls, `admin.py` (includes
  `OrderAdmin` — full order visibility/edit at `/admin/olretail/order/`),
  `context_processors.py` (categories + roles in every template),
  migrations 0001–0012
- `olretail/payment_models.py` / `payment_views.py` / `payment_forms.py` —
  cart/checkout/orders/payments/disputes/delivery tracking (courier
  assignment + required delivery photo), both Stripe (now correctly handles
  multi-seller carts — see Multi-seller Stripe checkout fix) and direct
  bank/mobile transfer (re-exported into `models.py`, see Payments section)
- `olretail/subscription_models.py` — `SellerSubscription` /
  `SubscriptionRequest` (seller listing-limit + paid plan tracking, re-
  exported into `models.py`), `seller_subscription` view lives in
  `payment_views.py`, form in `payment_forms.py`
- `olretail/payouts.py` + `management/commands/schedule_payouts.py` — seller
  payout batching (who's owed, not money movement — see Payments section)
- `olretail/management/commands/seed_demo_users.py` — demo/QA data generator
  (see Demo/seed data section)
- `dashboard/views.py` (`payouts`/`payouts_run`/`payout_detail`/
  `payout_action`, `subscriptions`/`subscription_detail`/`subscription_action`)
  — staff review/confirm UI at `/dashboard/payouts/` and `/dashboard/subscriptions/`
- `accounts/` — register/login/logout + password-reset URLs and templates;
  `roles.py` is the role registry (groups + profiles per account type)
- `templates/shared/` — base (favicon), header (logo, seller nav incl.
  Subscription link), footer, messages, product_grid, pagination,
  popular_category partials
- `templates/olretail/` — index, details (cart-purchasable gating), lista
  (seller dashboard, subscription usage banner), product_form
  (subscriber "publishes instantly" note), cart/checkout/payment/orders/
  disputes, `bank_transfer_instructions.html`, `seller_payment_settings.html`,
  `seller_subscription.html`, `courier_deliveries.html`
- `dashboard/templates/dashboard/subscriptions.html` /
  `subscription_detail.html` — admin subscription review UI
- `compile_translations.py` — .po → .mo compiler (no gettext needed)
