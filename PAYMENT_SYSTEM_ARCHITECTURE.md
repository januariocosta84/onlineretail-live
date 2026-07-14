# Payment System Architecture for TimorMart

**Date**: 2026-07-14  
**Target**: Production-ready payment infrastructure  
**Technology**: Django 5.2 LTS + Stripe API  
**Timeline**: 2-3 weeks (core implementation)

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Database Models](#database-models)
3. [Payment Flow](#payment-flow)
4. [API Endpoints](#api-endpoints)
5. [Implementation Guide](#implementation-guide)
6. [Security Considerations](#security-considerations)
7. [Testing Strategy](#testing-strategy)

---

## System Overview

### Architecture Diagram
```
┌─────────────────────────────────────────────────────────────────┐
│                        BUYER EXPERIENCE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Browse Products → Add to Cart → Checkout → Payment Form        │
│                                                 │                │
│                                                 ▼                │
│                      ┌──────────────────────────────────┐        │
│                      │    Stripe Payment Gateway        │        │
│                      │   (Hosted Payment Page/API)      │        │
│                      └──────────┬───────────────────────┘        │
│                                 │                                │
│                                 ▼                                │
│                   Success/Failure Webhook → Django Order Creation
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    PLATFORM BACKEND                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Order Model ──→ Payment Model ──→ Transaction Model            │
│      │                  │                    │                  │
│      ▼                  ▼                    ▼                   │
│  Order Status    Payment Status         Commission               │
│  Tracking        Processing            Calculation              │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Seller Dashboard: View Orders & Track Payments      │       │
│  │  Admin Dashboard: Revenue, Payouts, Disputes        │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    PAYOUT ENGINE                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Monthly Batch Job:                                            │
│    1. Calculate commissions from all orders                    │
│    2. Aggregate seller balances                                │
│    3. Create Payout records                                    │
│    4. Process via bank transfer / Stripe Connect               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Models

### 1. Cart Model (Shopping Cart)
```python
from django.db import models
from django.contrib.auth.models import User
from olretail.models import Product

class Cart(models.Model):
    """Shopping cart items for buyer before checkout."""
    
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='carts')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('buyer', 'product')  # One entry per product per buyer
        ordering = ['-added_at']
    
    def __str__(self):
        return f"{self.buyer.username} - {self.product.name} (qty: {self.quantity})"
    
    @property
    def line_total(self):
        """Total price for this line item."""
        return self.product.price * self.quantity
```

### 2. Order Model (Core)
```python
class OrderStatus(models.TextChoices):
    """Order lifecycle states."""
    PENDING_PAYMENT = 'pending_payment', _('Pending Payment')
    PAID = 'paid', _('Payment Received')
    PROCESSING = 'processing', _('Processing')
    SHIPPED = 'shipped', _('Shipped')
    DELIVERED = 'delivered', _('Delivered')
    CANCELLED = 'cancelled', _('Cancelled')
    REFUNDED = 'refunded', _('Refunded')

class Order(models.Model):
    """Master order record - one per buyer per transaction."""
    
    # Identifiers
    order_number = models.CharField(max_length=20, unique=True)  # ORD-20260714-001
    
    # Participants
    buyer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='orders')
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT)
    
    # Product
    product = models.ForeignKey('olretail.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price_per_unit = models.DecimalField(max_digits=13, decimal_places=2)
    
    # Totals
    subtotal = models.DecimalField(max_digits=13, decimal_places=2)  # Before fees
    commission_amount = models.DecimalField(max_digits=13, decimal_places=2, default=0)
    payment_fee = models.DecimalField(max_digits=13, decimal_places=2, default=0)  # Stripe fee
    total = models.DecimalField(max_digits=13, decimal_places=2)  # Final charged amount
    
    # Status & Timestamps
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING_PAYMENT,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Delivery Info
    delivery_address = models.TextField()
    delivery_phone = models.CharField(max_length=40)
    estimated_delivery = models.DateField(null=True, blank=True)
    
    # Notes
    buyer_notes = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['buyer', '-created_at']),
            models.Index(fields=['seller', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.order_number} - {self.buyer.username} - ${self.total}"
    
    def save(self, *args, **kwargs):
        # Auto-generate order number on creation
        if not self.order_number:
            from django.utils import timezone
            date_str = timezone.now().strftime('%Y%m%d')
            count = Order.objects.filter(order_number__startswith=f'ORD-{date_str}').count()
            self.order_number = f'ORD-{date_str}-{count + 1:03d}'
        super().save(*args, **kwargs)
```

### 3. Payment Model (Payment Processing)
```python
class PaymentStatus(models.TextChoices):
    """Payment states."""
    PENDING = 'pending', _('Pending')
    PROCESSING = 'processing', _('Processing')
    SUCCEEDED = 'succeeded', _('Succeeded')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')
    REFUNDED = 'refunded', _('Refunded')

class Payment(models.Model):
    """Payment transaction record (one per order)."""
    
    # Reference
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name='payment')
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True)  # pi_xxxx
    stripe_charge_id = models.CharField(max_length=255, blank=True)  # ch_xxxx (after success)
    
    # Amount
    amount_cents = models.BigIntegerField()  # $10.50 = 1050 (in cents for precision)
    currency = models.CharField(max_length=3, default='USD')  # Use local currency
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    
    # Payment Method
    payment_method_type = models.CharField(max_length=50)  # card, sepa_debit, etc.
    payment_method_last4 = models.CharField(max_length=4)  # Last 4 digits of card/account
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    succeeded_at = models.DateTimeField(null=True, blank=True)
    
    # Error Handling
    error_message = models.TextField(blank=True)
    
    # Webhook
    webhook_received = models.BooleanField(default=False)
    webhook_received_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"Payment {self.stripe_payment_intent_id} - {self.status}"
    
    @property
    def amount_dollars(self):
        """Convert cents to dollars."""
        return self.amount_cents / 100
```

### 4. Transaction Model (Commission Tracking)
```python
class TransactionType(models.TextChoices):
    """Transaction purpose."""
    COMMISSION = 'commission', _('Commission')
    REFUND = 'refund', _('Refund')
    ADJUSTMENT = 'adjustment', _('Adjustment')
    PAYOUT = 'payout', _('Payout')

class Transaction(models.Model):
    """Financial transaction: commission, refund, adjustment."""
    
    # Reference
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='transactions')
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT, related_name='transactions')
    
    # Amount
    amount_cents = models.BigIntegerField()  # Commission or refund amount
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    
    # Accounting
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['seller', '-created_at']),
            models.Index(fields=['transaction_type', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.transaction_type} - Seller {self.seller.user.username} - ${self.amount_cents / 100}"
    
    @property
    def amount_dollars(self):
        return self.amount_cents / 100
```

### 5. SellerBalance Model (Running Balance)
```python
class SellerBalance(models.Model):
    """Seller's account balance: commissions earned - payouts."""
    
    seller = models.OneToOneField('olretail.Seller', on_delete=models.CASCADE, related_name='balance')
    
    # Totals (in cents)
    total_earnings = models.BigIntegerField(default=0)  # All commissions
    total_payouts = models.BigIntegerField(default=0)  # Paid out so far
    pending_payout = models.BigIntegerField(default=0)  # Scheduled but not yet paid
    available_balance = models.BigIntegerField(default=0)  # Ready to withdraw
    
    # Minimum payout threshold
    min_payout_cents = models.BigIntegerField(default=50000)  # $500 minimum
    
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Balance: {self.seller.user.username} - ${self.available_balance / 100}"
    
    def add_commission(self, amount_cents):
        """Add commission to seller's balance."""
        self.total_earnings += amount_cents
        self.available_balance += amount_cents
        self.save()
    
    def schedule_payout(self, amount_cents):
        """Mark amount as scheduled for payout."""
        self.available_balance -= amount_cents
        self.pending_payout += amount_cents
        self.save()
    
    def complete_payout(self, amount_cents):
        """Mark payout as completed."""
        self.pending_payout -= amount_cents
        self.total_payouts += amount_cents
        self.save()
    
    @property
    def available_balance_dollars(self):
        return self.available_balance / 100
    
    @property
    def pending_payout_dollars(self):
        return self.pending_payout / 100
```

### 6. Payout Model (Seller Payouts)
```python
class PayoutStatus(models.TextChoices):
    """Payout states."""
    SCHEDULED = 'scheduled', _('Scheduled')
    PROCESSING = 'processing', _('Processing')
    PAID = 'paid', _('Paid')
    FAILED = 'failed', _('Failed')

class Payout(models.Model):
    """Seller payout batch (monthly or on-demand)."""
    
    # Reference
    payout_id = models.CharField(max_length=20, unique=True)  # PAY-20260730-001
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT, related_name='payouts')
    
    # Amount
    amount_cents = models.BigIntegerField()  # Total to pay
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=PayoutStatus.choices,
        default=PayoutStatus.SCHEDULED,
    )
    
    # Bank Details
    bank_name = models.CharField(max_length=255, blank=True)
    account_number = models.CharField(max_length=50, blank=True)  # Encrypted
    account_holder = models.CharField(max_length=255, blank=True)
    
    # Stripe Connect (if using Stripe for payouts)
    stripe_payout_id = models.CharField(max_length=255, blank=True)
    
    # Timing
    scheduled_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-scheduled_date']
        indexes = [
            models.Index(fields=['seller', 'status']),
            models.Index(fields=['status', '-scheduled_date']),
        ]
    
    def __str__(self):
        return f"{self.payout_id} - {self.seller.user.username} - ${self.amount_cents / 100}"
    
    def save(self, *args, **kwargs):
        # Auto-generate payout ID
        if not self.payout_id:
            from django.utils import timezone
            date_str = timezone.now().strftime('%Y%m%d')
            count = Payout.objects.filter(payout_id__startswith=f'PAY-{date_str}').count()
            self.payout_id = f'PAY-{date_str}-{count + 1:03d}'
        super().save(*args, **kwargs)
    
    @property
    def amount_dollars(self):
        return self.amount_cents / 100
```

### 7. Dispute Model (Buyer Protection)
```python
class DisputeStatus(models.TextChoices):
    """Dispute states."""
    OPEN = 'open', _('Open - Awaiting Seller Response')
    SELLER_RESPONSE = 'seller_response', _('Seller Responded')
    UNDER_REVIEW = 'under_review', _('Under Admin Review')
    RESOLVED = 'resolved', _('Resolved')
    CLOSED = 'closed', _('Closed')

class DisputeResolution(models.TextChoices):
    """Dispute outcomes."""
    REFUND_FULL = 'refund_full', _('Full Refund to Buyer')
    REFUND_PARTIAL = 'refund_partial', _('Partial Refund')
    RESHIPMENT = 'reshipment', _('Reshipment')
    CLOSED_NO_ACTION = 'no_action', _('Closed - No Action')

class Dispute(models.Model):
    """Buyer-initiated dispute (damaged, non-delivery, etc.)."""
    
    # Reference
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name='dispute')
    dispute_id = models.CharField(max_length=20, unique=True)  # DIS-20260714-001
    
    # Participants
    buyer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='disputes_initiated')
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT, related_name='disputes_received')
    
    # Content
    reason = models.CharField(max_length=100)  # damaged, not_arrived, not_as_described, etc.
    description = models.TextField()
    
    # Evidence
    buyer_evidence = models.TextField(blank=True)  # Photos, messages, etc.
    seller_response = models.TextField(blank=True)
    
    # Status
    status = models.CharField(
        max_length=30,
        choices=DisputeStatus.choices,
        default=DisputeStatus.OPEN,
    )
    
    # Resolution
    resolution = models.CharField(
        max_length=30,
        choices=DisputeResolution.choices,
        blank=True,
    )
    refund_amount = models.DecimalField(max_digits=13, decimal_places=2, default=0)
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    seller_response_deadline = models.DateTimeField()  # 3 days from creation
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Admin
    admin_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='disputes_resolved')
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['seller', 'status']),
        ]
    
    def __str__(self):
        return f"{self.dispute_id} - Order {self.order.order_number}"
    
    def save(self, *args, **kwargs):
        if not self.dispute_id:
            from django.utils import timezone
            date_str = timezone.now().strftime('%Y%m%d')
            count = Dispute.objects.filter(dispute_id__startswith=f'DIS-{date_str}').count()
            self.dispute_id = f'DIS-{date_str}-{count + 1:03d}'
        
        if not self.seller_response_deadline:
            from django.utils import timezone
            from datetime import timedelta
            self.seller_response_deadline = timezone.now() + timedelta(days=3)
        
        super().save(*args, **kwargs)
```

---

## Payment Flow

### Complete User Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. BROWSING PHASE                                               │
├─────────────────────────────────────────────────────────────────┤
│ Buyer views product → Clicks "Add to Cart"                      │
│                                                                  │
│ Backend: Create Cart entry (buyer, product, qty)               │
│ Status: Cart items stored in database                           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. CART REVIEW PHASE                                            │
├─────────────────────────────────────────────────────────────────┤
│ Buyer views cart → Reviews items & quantities                  │
│                                                                  │
│ Backend: Show cart total, calculate tax/fees if needed          │
│ Option: Buyer can update quantity or remove items              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. CHECKOUT INITIATION                                          │
├─────────────────────────────────────────────────────────────────┤
│ Buyer clicks "Proceed to Checkout"                              │
│                                                                  │
│ Backend:                                                         │
│   1. Validate inventory (check quantity still available)        │
│   2. Create Order record (status: PENDING_PAYMENT)              │
│   3. Calculate commission: subtotal × 0.15 (15%)               │
│   4. Calculate Stripe fee: total × 0.029 + 0.30                │
│   5. Calculate final total: subtotal + commission + fee         │
│   6. Create Payment record (status: PENDING)                    │
│   7. Create Stripe PaymentIntent (amount_cents, metadata)       │
│                                                                  │
│ Return: Stripe client_secret to frontend                        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. PAYMENT SUBMISSION                                           │
├─────────────────────────────────────────────────────────────────┤
│ Frontend (Stripe Elements/Hosted Checkout):                     │
│   - Show payment form (card details, email, address)           │
│   - Submit payment to Stripe (never touches server)            │
│                                                                  │
│ Stripe processes payment (3D Secure, fraud checks, etc.)       │
│                                                                  │
│ Response to Frontend:                                           │
│   ✅ Success → Redirect to /order/confirmation/               │
│   ❌ Failure → Show error, allow retry                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. WEBHOOK CONFIRMATION                                         │
├─────────────────────────────────────────────────────────────────┤
│ Stripe sends webhook: payment_intent.succeeded                 │
│                                                                  │
│ Backend:                                                         │
│   1. Verify webhook signature (security)                        │
│   2. Update Payment record:                                     │
│      - status: SUCCEEDED                                        │
│      - stripe_charge_id: ch_xxxxx                               │
│      - succeeded_at: timestamp                                  │
│   3. Update Order record:                                       │
│      - status: PAID                                             │
│      - paid_at: timestamp                                       │
│   4. Create Transaction record (commission)                     │
│   5. Update SellerBalance (add commission)                      │
│   6. Reduce Product quantity (inventory)                        │
│   7. Clear Cart items                                           │
│   8. Send confirmation emails (buyer, seller, admin)           │
│                                                                  │
│ Status: Order is now PAID and ready to ship                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. FULFILLMENT PHASE                                            │
├─────────────────────────────────────────────────────────────────┤
│ Seller views order in dashboard                                │
│ Seller packages item                                            │
│ Seller clicks "Mark as Shipped" → Sets tracking number         │
│                                                                  │
│ Backend:                                                         │
│   - Update Order status: SHIPPED                                │
│   - Send tracking email to buyer                                │
│                                                                  │
│ (After delivery confirmation or 7 days auto-complete)          │
│ - Update Order status: DELIVERED                                │
│ - Seller can now request payout                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. PAYOUT PHASE (Monthly Batch)                                 │
├─────────────────────────────────────────────────────────────────┤
│ Scheduled Celery job runs on 1st of each month:                │
│                                                                  │
│   1. Get all sellers with available_balance > $500 minimum     │
│   2. For each seller:                                           │
│      - Aggregate commission from all completed orders           │
│      - Create Payout record (status: SCHEDULED)                 │
│      - Call SellerBalance.schedule_payout(amount)              │
│   3. Process payouts:                                           │
│      - Via Stripe Connect API, OR                               │
│      - Via bank transfer API                                    │
│   4. Update Payout.status → PAID                               │
│   5. Update SellerBalance.complete_payout(amount)              │
│   6. Send payout confirmation email to seller                   │
│                                                                  │
│ Seller receives money in bank account within 2-5 business days │
└─────────────────────────────────────────────────────────────────┘
```

### Failure Scenarios

**Scenario 1: Payment Declined**
```
Stripe declines payment (insufficient funds, etc.)
↓
Webhook: payment_intent.payment_failed
↓
Backend:
  - Update Payment.status → FAILED
  - Update Payment.error_message → "Card declined"
  - Keep Order.status as PENDING_PAYMENT
  - Send email to buyer: "Payment failed, please retry"
↓
Buyer clicks "Retry Payment" → Re-create Stripe PaymentIntent
```

**Scenario 2: Buyer Initiates Dispute**
```
Order DELIVERED but buyer claims item damaged
↓
Buyer opens dispute form:
  - Reason: "Product arrived damaged"
  - Description: "Screen cracked, not usable"
  - Upload photo evidence
↓
Backend:
  - Create Dispute record (status: OPEN)
  - Send email to seller: "Dispute filed, respond within 3 days"
  - Set deadline: seller_response_deadline = now + 3 days
↓
Seller responds with evidence or refuses
↓
Admin reviews and decides:
  - Full refund: Refund payment via Stripe, adjust commissions
  - Partial refund: Return $X to buyer, keep commission
  - Reshipment: Seller ships replacement
  - No action: Close dispute
```

---

## API Endpoints

### Cart Management
```
POST   /cart/add/              → Add product to cart
GET    /cart/                  → View cart
POST   /cart/update/           → Update item quantity
POST   /cart/remove/           → Remove item from cart
POST   /cart/clear/            → Empty cart
```

### Checkout & Payment
```
POST   /checkout/              → Initiate checkout (create Order + Payment)
  Request:
    {
      "cart_items": [...],
      "delivery_address": "123 Main St",
      "delivery_phone": "7012345",
      "buyer_notes": "Please knock loudly"
    }
  Response:
    {
      "order_id": "ORD-20260714-001",
      "stripe_client_secret": "pi_xxx#secret_xxx",
      "amount_cents": 10050,
      "commission_amount": 1350,
      "payment_fee": 30
    }

GET    /order/{order_id}/      → View order details
POST   /order/{order_id}/cancel/ → Cancel unpaid order
```

### Admin/Seller Endpoints
```
GET    /seller/orders/         → Seller's orders
GET    /seller/balance/        → Seller's balance & earnings
GET    /seller/payouts/        → Seller's payout history
POST   /seller/request-payout/ → Request manual payout (if > min)

GET    /admin/revenue/         → Admin dashboard (revenue, GMV, etc.)
GET    /admin/transactions/    → Transaction history
GET    /admin/payouts/         → Payout batch status
POST   /admin/process-payouts/ → Trigger manual payout batch
GET    /admin/disputes/        → List disputes
POST   /admin/dispute/{id}/resolve/ → Admin resolution
```

### Webhook (Stripe)
```
POST   /webhook/stripe/        → Receive payment status updates from Stripe
  Events handled:
    - payment_intent.succeeded
    - payment_intent.payment_failed
    - charge.refunded
    - payout.paid (if using Stripe payouts)
```

---

## Implementation Guide

### Step 1: Install Dependencies

```bash
# Install Stripe SDK
pip install stripe django-environ python-decouple

# Add to requirements.txt
stripe>=5.4
django-environ>=0.10
```

### Step 2: Create Models File

Create `olretail/payment_models.py`:

```python
# [Insert models from "Database Models" section above]
```

### Step 3: Create Forms

Create `olretail/payment_forms.py`:

```python
from django import forms
from .payment_models import Order, Cart

class CheckoutForm(forms.Form):
    """Delivery information for checkout."""
    
    delivery_address = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Street, City, Region'}),
        label="Delivery Address"
    )
    delivery_phone = forms.CharField(
        max_length=40,
        widget=forms.TextInput(attrs={'placeholder': '7012345 or +670 7012345'}),
        label="Delivery Phone"
    )
    buyer_notes = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Any special instructions?'}),
        label="Special Instructions (Optional)"
    )
```

### Step 4: Create Views

Create `olretail/payment_views.py`:

```python
import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

# ──────────────────────────────────────────────────────────────────
# CART VIEWS
# ──────────────────────────────────────────────────────────────────

@login_required
def cart(request):
    """Display shopping cart."""
    cart_items = Cart.objects.filter(buyer=request.user).select_related('product')
    
    context = {
        'cart_items': cart_items,
        'cart_total': sum(item.line_total for item in cart_items),
    }
    return render(request, 'olretail/cart.html', context)

@login_required
@require_POST
def add_to_cart(request, product_id):
    """Add product to cart."""
    from olretail.models import Product
    
    product = get_object_or_404(Product, id=product_id)
    quantity = int(request.POST.get('quantity', 1))
    
    cart_item, created = Cart.objects.get_or_create(
        buyer=request.user,
        product=product,
        defaults={'quantity': quantity}
    )
    
    if not created:
        cart_item.quantity += quantity
        cart_item.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'added', 'cart_count': Cart.objects.filter(buyer=request.user).count()})
    
    return redirect('olretail:cart')

@login_required
@require_POST
def update_cart(request, cart_id):
    """Update cart item quantity."""
    from django.contrib.auth.decorators import login_required
    
    cart_item = get_object_or_404(Cart, id=cart_id, buyer=request.user)
    quantity = int(request.POST.get('quantity', 1))
    
    if quantity > 0:
        cart_item.quantity = quantity
        cart_item.save()
    else:
        cart_item.delete()
    
    return redirect('olretail:cart')

@login_required
@require_POST
def remove_from_cart(request, cart_id):
    """Remove item from cart."""
    cart_item = get_object_or_404(Cart, id=cart_id, buyer=request.user)
    cart_item.delete()
    return redirect('olretail:cart')

# ──────────────────────────────────────────────────────────────────
# CHECKOUT VIEWS
# ──────────────────────────────────────────────────────────────────

@login_required
def checkout(request):
    """Checkout form: collect delivery info."""
    from .payment_forms import CheckoutForm
    
    cart_items = Cart.objects.filter(buyer=request.user).select_related('product')
    
    if not cart_items.exists():
        return redirect('olretail:cart')
    
    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            return _process_checkout(request, form, cart_items)
    else:
        # Pre-fill form with buyer's address if available
        buyer_profile = request.user.buyer
        form = CheckoutForm(initial={
            'delivery_address': buyer_profile.address if buyer_profile else '',
            'delivery_phone': buyer_profile.mobile if buyer_profile else '',
        })
    
    cart_total = sum(item.line_total for item in cart_items)
    
    context = {
        'form': form,
        'cart_items': cart_items,
        'cart_total': cart_total,
    }
    return render(request, 'olretail/checkout.html', context)

def _process_checkout(request, form, cart_items):
    """Create order and payment intent."""
    from olretail.models import Product
    from .payment_models import Order, Payment, OrderStatus, PaymentStatus
    
    # Validate inventory
    for item in cart_items:
        if item.quantity > item.product.quantity:
            return render(request, 'olretail/checkout_error.html', {
                'error': f"{item.product.name} is out of stock"
            })
    
    # Calculate totals
    subtotal_cents = int(sum(item.line_total * 100 for item in cart_items))
    commission_percent = Decimal('0.15')  # 15%
    commission_cents = int(subtotal_cents * float(commission_percent))
    
    # Stripe processing fee
    stripe_fee_percent = Decimal('0.029')  # 2.9%
    stripe_fee_fixed_cents = 30  # $0.30
    total_cents = subtotal_cents + commission_cents
    payment_fee_cents = int(total_cents * float(stripe_fee_percent)) + stripe_fee_fixed_cents
    
    final_total_cents = total_cents + payment_fee_cents
    
    # Create orders (one per seller)
    sellers_products = {}
    for item in cart_items:
        seller = item.product.seller
        if seller not in sellers_products:
            sellers_products[seller] = []
        sellers_products[seller].append(item)
    
    orders = []
    for seller, items in sellers_products.items():
        for item in items:
            order = Order.objects.create(
                buyer=request.user,
                seller=seller,
                product=item.product,
                quantity=item.quantity,
                price_per_unit=item.product.price,
                subtotal=item.line_total,
                commission_amount=item.line_total * commission_percent,
                payment_fee=Decimal(payment_fee_cents) / 100,
                total=item.line_total + (item.line_total * commission_percent) + (Decimal(payment_fee_cents) / 100),
                status=OrderStatus.PENDING_PAYMENT,
                delivery_address=form.cleaned_data['delivery_address'],
                delivery_phone=form.cleaned_data['delivery_phone'],
                buyer_notes=form.cleaned_data.get('buyer_notes', ''),
            )
            orders.append(order)
    
    # Create payment (one per order, for now group all)
    # For simplicity, create a single payment for first order; in production, handle multiple
    primary_order = orders[0]
    
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=final_total_cents,
            currency='usd',  # Change to local currency
            metadata={
                'order_id': primary_order.order_number,
                'buyer_id': request.user.id,
                'order_count': len(orders),
            },
        )
        
        payment = Payment.objects.create(
            order=primary_order,
            stripe_payment_intent_id=payment_intent['id'],
            amount_cents=final_total_cents,
            status=PaymentStatus.PENDING,
            payment_method_type='card',
        )
        
        # Store order IDs in session for webhook linking
        request.session['order_ids'] = [o.id for o in orders]
        
        return render(request, 'olretail/payment.html', {
            'order': primary_order,
            'payment': payment,
            'client_secret': payment_intent['client_secret'],
            'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
            'orders': orders,
        })
    
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        return render(request, 'olretail/checkout_error.html', {
            'error': 'Payment processing error. Please try again.'
        })

@login_required
def payment_confirmation(request, order_id):
    """Confirmation page after successful payment."""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    
    context = {
        'order': order,
    }
    return render(request, 'olretail/payment_confirmation.html', context)

# ──────────────────────────────────────────────────────────────────
# WEBHOOK (Stripe)
# ──────────────────────────────────────────────────────────────────

@require_POST
def stripe_webhook(request):
    """Handle Stripe webhook events."""
    from .payment_models import Order, Payment, PaymentStatus, OrderStatus, Transaction, TransactionType, SellerBalance
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    except stripe.error.SignatureVerificationError:
        return JsonResponse({'error': 'Invalid signature'}, status=400)
    
    # Handle payment success
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        order_id = payment_intent['metadata'].get('order_id')
        
        try:
            order = Order.objects.get(order_number=order_id)
            payment = order.payment
            
            # Update payment
            payment.stripe_charge_id = payment_intent['charges']['data'][0]['id']
            payment.status = PaymentStatus.SUCCEEDED
            payment.succeeded_at = timezone.now()
            payment.webhook_received = True
            payment.webhook_received_at = timezone.now()
            payment.save()
            
            # Update order
            order.status = OrderStatus.PAID
            order.paid_at = timezone.now()
            order.save()
            
            # Create transaction (commission)
            transaction = Transaction.objects.create(
                order=order,
                seller=order.seller,
                amount_cents=int(order.commission_amount * 100),
                transaction_type=TransactionType.COMMISSION,
                description=f"Commission on order {order.order_number}",
            )
            
            # Update seller balance
            seller_balance, _ = SellerBalance.objects.get_or_create(seller=order.seller)
            seller_balance.add_commission(int(order.commission_amount * 100))
            
            # Reduce product inventory
            order.product.quantity -= order.quantity
            order.product.save()
            
            # Clear cart
            Cart.objects.filter(buyer=order.buyer, product=order.product).delete()
            
            # Send confirmation emails (TODO: implement email service)
            logger.info(f"Payment succeeded for order {order.order_number}")
            
        except Order.DoesNotExist:
            logger.error(f"Order not found: {order_id}")
            return JsonResponse({'error': 'Order not found'}, status=404)
    
    # Handle payment failure
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        order_id = payment_intent['metadata'].get('order_id')
        
        try:
            order = Order.objects.get(order_number=order_id)
            payment = order.payment
            
            payment.status = PaymentStatus.FAILED
            payment.error_message = payment_intent.get('last_payment_error', {}).get('message', '')
            payment.webhook_received = True
            payment.webhook_received_at = timezone.now()
            payment.save()
            
            logger.warning(f"Payment failed for order {order.order_number}: {payment.error_message}")
            
        except Order.DoesNotExist:
            logger.error(f"Order not found: {order_id}")
    
    return JsonResponse({'status': 'success'})
```

### Step 5: Create Templates

Create `olretail/templates/olretail/cart.html`:

```html
{% extends "shared/base.html" %}
{% load i18n %}

{% block title %}{% trans "Shopping Cart" %} | TimorMart{% endblock %}

{% block content %}
<main class="py-5">
  <div class="container">
    <h1 class="mb-4">{% trans "Shopping Cart" %}</h1>
    
    {% if cart_items %}
      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th>{% trans "Product" %}</th>
              <th>{% trans "Price" %}</th>
              <th>{% trans "Quantity" %}</th>
              <th>{% trans "Total" %}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {% for item in cart_items %}
            <tr>
              <td>
                <a href="{{ item.product.get_absolute_url }}">{{ item.product.name }}</a>
              </td>
              <td>${{ item.product.price }}</td>
              <td>
                <form method="post" action="{% url 'olretail:update_cart' item.id %}" class="form-inline">
                  {% csrf_token %}
                  <input type="number" name="quantity" value="{{ item.quantity }}" min="1" max="{{ item.product.quantity }}" class="form-control form-control-sm w-50">
                  <button type="submit" class="btn btn-sm btn-secondary">{% trans "Update" %}</button>
                </form>
              </td>
              <td>${{ item.line_total }}</td>
              <td>
                <form method="post" action="{% url 'olretail:remove_from_cart' item.id %}" class="d-inline">
                  {% csrf_token %}
                  <button type="submit" class="btn btn-sm btn-danger">{% trans "Remove" %}</button>
                </form>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      
      <div class="row mt-4">
        <div class="col-md-8"></div>
        <div class="col-md-4">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">{% trans "Order Summary" %}</h5>
              <p>
                {% trans "Subtotal" %}: <strong>${{ cart_total }}</strong>
              </p>
              <a href="{% url 'olretail:checkout' %}" class="btn btn-primary btn-block">
                {% trans "Proceed to Checkout" %}
              </a>
            </div>
          </div>
        </div>
      </div>
    {% else %}
      <div class="alert alert-info">
        {% trans "Your cart is empty." %}
        <a href="{% url 'olretail:index' %}">{% trans "Continue shopping" %}</a>
      </div>
    {% endif %}
  </div>
</main>
{% endblock %}
```

Create `olretail/templates/olretail/payment.html`:

```html
{% extends "shared/base.html" %}
{% load i18n %}

{% block title %}{% trans "Payment" %} | TimorMart{% endblock %}

{% block extra_head %}
<script src="https://js.stripe.com/v3/"></script>
{% endblock %}

{% block content %}
<main class="py-5">
  <div class="container">
    <div class="row justify-content-center">
      <div class="col-lg-8">
        <h1 class="mb-4">{% trans "Payment" %}</h1>
        
        <div class="card mb-4">
          <div class="card-body">
            <h5 class="card-title">{% trans "Order Summary" %}</h5>
            <p>{% trans "Order #" %}: {{ order.order_number }}</p>
            <p>{{ order.product.name }} × {{ order.quantity }}</p>
            <hr>
            <p>
              {% trans "Subtotal" %}: ${{ order.subtotal }}<br>
              {% trans "Commission" %}: ${{ order.commission_amount }}<br>
              {% trans "Processing Fee" %}: ${{ order.payment_fee }}<br>
              <strong>{% trans "Total" %}: ${{ order.total }}</strong>
            </p>
          </div>
        </div>
        
        <div class="card">
          <div class="card-body">
            <h5 class="card-title">{% trans "Card Details" %}</h5>
            <form id="payment-form">
              <div id="card-element" class="form-control mb-3"></div>
              <button id="submit-button" type="submit" class="btn btn-primary btn-block">
                {% trans "Pay" %} ${{ order.total }}
              </button>
              <div id="payment-message" class="mt-2"></div>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>
</main>

<script>
const stripe = Stripe('{{ stripe_public_key }}');
const elements = stripe.elements();
const cardElement = elements.create('card');
cardElement.mount('#card-element');

const form = document.getElementById('payment-form');
const clientSecret = '{{ client_secret }}';

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const { error } = await stripe.confirmCardPayment(clientSecret, {
    payment_method: {
      card: cardElement,
      billing_details: {}
    }
  });
  
  if (error) {
    document.getElementById('payment-message').textContent = error.message;
  } else {
    window.location.href = "{% url 'olretail:payment_confirmation' order.id %}";
  }
});
</script>
{% endblock %}
```

### Step 6: Update URLs

Add to `olretail/urls.py`:

```python
from django.urls import path
from . import views, payment_views

app_name = 'olretail'

urlpatterns = [
    # ... existing patterns ...
    
    # Cart
    path('cart/', payment_views.cart, name='cart'),
    path('cart/add/<int:product_id>/', payment_views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:cart_id>/', payment_views.update_cart, name='update_cart'),
    path('cart/remove/<int:cart_id>/', payment_views.remove_from_cart, name='remove_from_cart'),
    
    # Checkout & Payment
    path('checkout/', payment_views.checkout, name='checkout'),
    path('payment/<int:order_id>/confirmation/', payment_views.payment_confirmation, name='payment_confirmation'),
    
    # Webhook
    path('webhook/stripe/', payment_views.stripe_webhook, name='stripe_webhook'),
]
```

### Step 7: Settings Configuration

Add to `TLoretail/settings.py`:

```python
# Stripe Configuration
STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY', 'pk_test_...')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_...')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', 'whsec_...')

# Payment Configuration
COMMISSION_RATE = 0.15  # 15%
STRIPE_FEE_PERCENT = 0.029  # 2.9%
STRIPE_FEE_FIXED = 0.30  # $0.30

MIN_PAYOUT_AMOUNT = 50000  # $500 in cents
PAYOUT_SCHEDULE = 'monthly'  # 'daily', 'weekly', 'monthly'
```

### Step 8: Run Migrations

```bash
python manage.py makemigrations olretail
python manage.py migrate
```

---

## Security Considerations

### 1. **PCI Compliance**
- ✅ Never store card data on your server
- ✅ Use Stripe Elements (hosted payment form)
- ✅ Offload all card processing to Stripe
- ❌ Don't implement your own payment processing

### 2. **Webhook Verification**
```python
# ALWAYS verify webhook signature
sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
try:
    event = stripe.Webhook.construct_event(
        payload, sig_header, STRIPE_WEBHOOK_SECRET
    )
except stripe.error.SignatureVerificationError:
    return JsonResponse({'error': 'Invalid signature'}, status=400)
```

### 3. **HTTPS Only**
```python
# Enforce HTTPS
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

### 4. **Idempotency Keys**
```python
# Prevent duplicate charges if webhook retries
import uuid
idempotency_key = str(uuid.uuid4())

payment_intent = stripe.PaymentIntent.create(
    ...,
    idempotency_key=idempotency_key,
)
```

### 5. **Rate Limiting**
```python
# Protect payment endpoints from abuse
from django_ratelimit.decorators import ratelimit

@ratelimit(key='user', rate='10/h', method='POST')
@require_POST
def checkout(request):
    ...
```

### 6. **Logging & Monitoring**
```python
# Log all payment events for audit trail
logger.info(f"Payment received: {order.order_number}, Amount: ${order.total}")
logger.error(f"Payment failed: {order.order_number}, Reason: {error_message}")

# Monitor for suspicious patterns
# - Multiple failed payments from same card
# - Chargebacks
# - Refund rate > threshold
```

---

## Testing Strategy

### Unit Tests

```python
# olretail/tests/test_payments.py

from django.test import TestCase, Client
from django.contrib.auth.models import User
from olretail.models import Product, Seller
from olretail.payment_models import Order, Payment, SellerBalance
from decimal import Decimal

class PaymentTests(TestCase):
    
    def setUp(self):
        self.client = Client()
        self.buyer = User.objects.create_user(username='buyer', password='pass123')
        self.seller_user = User.objects.create_user(username='seller', password='pass123')
        self.seller = Seller.objects.create(user=self.seller_user, mobile='7012345', address='123 Main St')
        
        self.product = Product.objects.create(
            name='Test Product',
            slug='test-product',
            price=Decimal('100.00'),
            quantity=10,
            seller=self.seller,
            category_id=1,
            country_id=1,
            item_location_id=1,
            description='Test',
            status='approved',
        )
    
    def test_order_creation(self):
        """Test order is created correctly."""
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            product=self.product,
            quantity=1,
            price_per_unit=self.product.price,
            subtotal=Decimal('100.00'),
            commission_amount=Decimal('15.00'),
            total=Decimal('115.00'),
            delivery_address='123 Main St',
            delivery_phone='7012345',
        )
        
        self.assertEqual(order.buyer, self.buyer)
        self.assertEqual(order.product, self.product)
        self.assertEqual(order.status, 'pending_payment')
        self.assertIsNotNone(order.order_number)
    
    def test_commission_calculation(self):
        """Test commission is 15% of subtotal."""
        subtotal = Decimal('100.00')
        commission = subtotal * Decimal('0.15')
        
        self.assertEqual(commission, Decimal('15.00'))
    
    def test_seller_balance_update(self):
        """Test seller balance increases on payment."""
        seller_balance, _ = SellerBalance.objects.get_or_create(seller=self.seller)
        commission_cents = 1500  # $15.00
        
        seller_balance.add_commission(commission_cents)
        seller_balance.refresh_from_db()
        
        self.assertEqual(seller_balance.total_earnings, commission_cents)
        self.assertEqual(seller_balance.available_balance, commission_cents)
```

### Integration Tests

```python
def test_full_checkout_flow(self):
    """Test complete checkout and payment."""
    # 1. Add to cart
    response = self.client.post(
        reverse('olretail:add_to_cart', args=[self.product.id]),
        {'quantity': 1},
        HTTP_X_REQUESTED_WITH='XMLHttpRequest'
    )
    self.assertEqual(response.status_code, 200)
    
    # 2. Initiate checkout
    response = self.client.post(
        reverse('olretail:checkout'),
        {
            'delivery_address': '123 Main St',
            'delivery_phone': '7012345',
            'buyer_notes': 'Please knock',
        }
    )
    self.assertEqual(response.status_code, 200)
    self.assertIn('stripe_client_secret', response.context)
```

### Stripe Mock Testing

```python
# Mock Stripe responses in tests
import stripe
from unittest.mock import patch

@patch('stripe.PaymentIntent.create')
def test_payment_intent_creation(self, mock_create):
    """Test payment intent is created."""
    mock_create.return_value = {
        'id': 'pi_test123',
        'client_secret': 'pi_test123_secret_xxx',
        'amount': 10050,
        'status': 'requires_payment_method',
    }
    
    # Trigger payment intent creation
    response = self.client.post(reverse('olretail:checkout'), {...})
    
    # Verify Stripe was called
    mock_create.assert_called_once()
```

---

## Deployment Checklist

- [ ] Set `DEBUG = False` in production
- [ ] Set `STRIPE_SECRET_KEY` environment variable
- [ ] Set `STRIPE_PUBLIC_KEY` environment variable
- [ ] Set `STRIPE_WEBHOOK_SECRET` environment variable
- [ ] Configure Stripe webhook endpoint in Stripe Dashboard
- [ ] Enable HTTPS (DJANGO_SSL_REDIRECT=true)
- [ ] Run security checks: `python manage.py check --deploy`
- [ ] Set up logging & monitoring (Sentry, CloudWatch)
- [ ] Set up database backups
- [ ] Test webhook delivery in Stripe Dashboard
- [ ] Soft launch with 10-20 test transactions

---

## Conclusion

This payment system architecture provides:

✅ **Complete payment flow** from cart → checkout → payment → payout  
✅ **Security** with Stripe handling sensitive data  
✅ **Scalability** with batched monthly payouts  
✅ **Dispute resolution** for buyer protection  
✅ **Commission tracking** for revenue accounting  
✅ **Seller transparency** via balance dashboard  

**Estimated Implementation Time**: 2-3 weeks for a developer familiar with Django & Stripe.

Ready to start building? Let me know if you have questions about any section!

