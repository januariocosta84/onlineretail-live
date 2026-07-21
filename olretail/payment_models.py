from django.db import IntegrityError, models, transaction
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


# ──────────────────────────────────────────────────────────────────
# CART MODEL
# ──────────────────────────────────────────────────────────────────

class Cart(models.Model):
    """Shopping cart items for buyer before checkout."""
    
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='carts')
    product = models.ForeignKey('olretail.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Set once a reminder email has been sent for this line item — prevents
    # the abandoned-cart sweep from emailing the same buyer repeatedly.
    # Cleared (via delete, same as the row itself) once the item is bought
    # or removed, so a later abandon of a re-added item reminds again.
    abandoned_reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('buyer', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.buyer.username} - {self.product.name} (qty: {self.quantity})"

    @property
    def line_total(self):
        """Total price for this line item."""
        return self.product.price * self.quantity


class Wishlist(models.Model):
    """A buyer's saved-for-later products — separate from Cart, no
    quantity/checkout involvement, just a bookmark list."""

    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey('olretail.Product', on_delete=models.CASCADE, related_name='wishlisted_by')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('buyer', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.buyer.username} - {self.product.name}"


# ──────────────────────────────────────────────────────────────────
# ORDER MODEL
# ──────────────────────────────────────────────────────────────────

class OrderStatus(models.TextChoices):
    """Order lifecycle states."""
    PENDING_PAYMENT = 'pending_payment', _('Pending Payment')
    PAYMENT_REPORTED = 'payment_reported', _('Payment Reported — Awaiting Confirmation')
    PAID = 'paid', _('Payment Received')
    PROCESSING = 'processing', _('Processing')
    SHIPPED = 'shipped', _('Shipped')
    DELIVERED = 'delivered', _('Delivered')
    CANCELLED = 'cancelled', _('Cancelled')
    REFUNDED = 'refunded', _('Refunded')


class FoodOrderStatus(models.TextChoices):
    """Finer-grained sub-states for restaurant orders, layered on top of the
    Order.status lifecycle above (which stays paid -> shipped -> delivered
    for every order type, food included — this just tracks the kitchen/
    pickup/transit progress in between). Delivered reuses the existing
    top-level OrderStatus.DELIVERED rather than duplicating it here."""
    RECEIVED = 'received', _('Order Received')
    PREPARING = 'preparing', _('Preparing Food')
    READY_FOR_PICKUP = 'ready_for_pickup', _('Ready for Pickup')
    PICKED_UP = 'picked_up', _('Picked Up')
    ON_THE_WAY = 'on_the_way', _('On the Way')


class PaymentMethod(models.TextChoices):
    """How the buyer pays for an order."""
    STRIPE = 'stripe', _('Card (Stripe)')
    BANK_TRANSFER = 'bank_transfer', _('Bank / Mobile Transfer')
    SIMULATED_BANK = 'simulated_bank', _('Automated Bank Transfer (Test)')


class Order(models.Model):
    """Master order record - one per buyer per product."""
    
    # Identifiers
    order_number = models.CharField(max_length=20, unique=True)
    
    # Participants
    buyer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='orders')
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT)
    
    # Product
    product = models.ForeignKey('olretail.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price_per_unit = models.DecimalField(max_digits=13, decimal_places=2)
    
    # Totals
    subtotal = models.DecimalField(max_digits=13, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=13, decimal_places=2, default=0)
    payment_fee = models.DecimalField(max_digits=13, decimal_places=2, default=0)
    # Restaurant orders only — flat fee per City.delivery_fee, charged once
    # per restaurant per checkout (not per item), added to this order's total.
    delivery_fee = models.DecimalField(max_digits=13, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=13, decimal_places=2)
    
    # Status & Timestamps
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING_PAYMENT,
        db_index=True,
    )
    # Restaurant orders only — blank/unset for every other order type.
    food_status = models.CharField(
        max_length=20, choices=FoodOrderStatus.choices, blank=True,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.STRIPE,
    )
    # A single Stripe charge can cover a cart spanning several sellers, so
    # many orders can share one Payment (contrast with the OneToOne it used
    # to be, which silently dropped every order but the first).
    payment = models.ForeignKey(
        'Payment', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    payment_reported_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # Delivery Info
    delivery_address = models.TextField()
    delivery_city = models.ForeignKey(
        'olretail.City', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    delivery_phone = models.CharField(max_length=40)
    estimated_delivery = models.DateField(null=True, blank=True)
    courier_name = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    assigned_courier = models.ForeignKey(
        'olretail.Courier', on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries'
    )
    delivery_photo = models.ImageField(upload_to='delivery_proofs/%Y/%m/', null=True, blank=True)
    
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
        # Auto-generate order number on creation. Wrapped in its own
        # savepoint with a retry: two concurrent checkouts can compute the
        # same count() and collide on the unique constraint — recomputing
        # and retrying (rather than letting IntegrityError bubble up as a
        # 500) keeps this safe under real concurrency.
        if self.order_number:
            super().save(*args, **kwargs)
            return

        for _attempt in range(5):
            date_str = timezone.now().strftime('%Y%m%d')
            # Max existing suffix, not count() — count() undercounts (and
            # permanently collides) once any order for today has been
            # deleted, leaving a gap in the sequence.
            last_order_number = (
                Order.objects.filter(order_number__startswith=f'ORD-{date_str}-')
                .order_by('-order_number')
                .values_list('order_number', flat=True)
                .first()
            )
            last_seq = int(last_order_number.rsplit('-', 1)[-1]) if last_order_number else 0
            self.order_number = f'ORD-{date_str}-{last_seq + 1:03d}'
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                self.order_number = ''
        raise IntegrityError('Could not generate a unique order_number after 5 attempts')


class DeliveryUpdate(models.Model):
    """Free-text status update the seller posts so the buyer can see
    progress (no courier tracking API — this is manual, like the courier
    itself). E.g. 'Left Dili warehouse, arriving Baucau tomorrow'."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='delivery_updates')
    note = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_number}: {self.note[:40]}"


class Notification(models.Model):
    """In-app notification for one user, optionally tied to an order —
    e.g. 'buyer sent payment', 'seller confirmed payment', 'order shipped'.
    Read via the bell icon in the header (see context_processors.notifications)
    or the full list at /notifications/."""

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    order = models.ForeignKey(
        'olretail.Order', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications'
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"{self.recipient.username}: {self.message}"


class Rating(models.Model):
    """A buyer's 1-5 star rating for a product, tied to the specific
    Delivered order that earned them the right to rate it — one rating per
    order, so a buyer can't rate a product they haven't actually received
    (and can rate again on a repeat purchase)."""

    SCORE_CHOICES = [(i, str(i)) for i in range(1, 6)]

    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ratings')
    product = models.ForeignKey('olretail.Product', on_delete=models.CASCADE, related_name='ratings')
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='rating')
    score = models.PositiveSmallIntegerField(choices=SCORE_CHOICES)
    # Optional written review — every Rating is already tied to a Delivered
    # Order the buyer placed, so this is inherently a verified-purchase
    # review with no separate gating needed.
    review_text = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.buyer.username} rated {self.product.name}: {self.score}/5"


class CourierRating(models.Model):
    """A buyer's 1-5 star rating for the courier who delivered their order —
    separate from the product Rating above, since a slow/rude courier is a
    different problem than a bad product. One rating per order."""

    SCORE_CHOICES = Rating.SCORE_CHOICES

    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='courier_ratings_given')
    courier = models.ForeignKey('olretail.Courier', on_delete=models.CASCADE, related_name='ratings')
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='courier_rating')
    score = models.PositiveSmallIntegerField(choices=SCORE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.buyer.username} rated courier {self.courier.get_name}: {self.score}/5"


# ──────────────────────────────────────────────────────────────────
# PAYMENT MODEL
# ──────────────────────────────────────────────────────────────────

class PaymentStatus(models.TextChoices):
    """Payment states."""
    PENDING = 'pending', _('Pending')
    PROCESSING = 'processing', _('Processing')
    SUCCEEDED = 'succeeded', _('Succeeded')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')
    REFUNDED = 'refunded', _('Refunded')


class Payment(models.Model):
    """Payment transaction record — one per gateway charge/transfer. A
    checkout can span several sellers/orders at once (see Order.payment), so
    this is not one-to-one with Order."""

    # Nullable so non-Stripe gateways (which have their own reference field
    # below) don't need a fake value here — SQL allows multiple NULLs under
    # a unique constraint, unlike multiple ''.
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True)

    # Which gateway processed this payment, and its external reference —
    # generic equivalent of stripe_payment_intent_id for non-Stripe gateways
    # (kept separate rather than repurposing the Stripe field, since a real
    # bank integration later needs its own honestly-named reference).
    gateway = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.STRIPE,
    )
    gateway_reference = models.CharField(max_length=255, blank=True, db_index=True)

    # Amount (in cents for precision)
    amount_cents = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='USD')
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    
    # Payment Method
    payment_method_type = models.CharField(max_length=50)
    payment_method_last4 = models.CharField(max_length=4, blank=True)
    
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
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Payment {self.stripe_payment_intent_id} - {self.status}"
    
    @property
    def amount_dollars(self):
        """Convert cents to dollars."""
        return self.amount_cents / 100


# ──────────────────────────────────────────────────────────────────
# TRANSACTION MODEL (Commission Tracking)
# ──────────────────────────────────────────────────────────────────

class TransactionType(models.TextChoices):
    """Transaction purpose. The stored value 'commission' predates this
    label fix and is left as-is (other code and any historical rows key off
    it) — only the human-readable label changed, since these entries record
    what a seller earned from a sale, not the platform's commission cut."""
    COMMISSION = 'commission', _('Order earnings')
    REFUND = 'refund', _('Refund')
    ADJUSTMENT = 'adjustment', _('Adjustment')
    PAYOUT = 'payout', _('Payout')


class Transaction(models.Model):
    """Financial transaction: commission, refund, adjustment."""
    
    # Reference
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='transactions')
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT, related_name='transactions')
    
    # Amount (in cents)
    amount_cents = models.BigIntegerField()
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
        return f"{self.transaction_type} - {self.seller.user.username} - ${self.amount_dollars:.2f}"
    
    @property
    def amount_dollars(self):
        return self.amount_cents / 100


# ──────────────────────────────────────────────────────────────────
# SELLER BALANCE MODEL
# ──────────────────────────────────────────────────────────────────

class SellerBalance(models.Model):
    """Seller's account balance: commissions earned - payouts."""
    
    seller = models.OneToOneField('olretail.Seller', on_delete=models.CASCADE, related_name='balance')
    
    # Totals (in cents)
    total_earnings = models.BigIntegerField(default=0)
    total_payouts = models.BigIntegerField(default=0)
    pending_payout = models.BigIntegerField(default=0)
    available_balance = models.BigIntegerField(default=0)
    
    # Minimum payout threshold
    min_payout_cents = models.BigIntegerField(default=50000)  # $500 minimum
    
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Balance: {self.seller.user.username} - ${self.available_balance_dollars:.2f}"
    
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

    def fail_payout(self, amount_cents):
        """Return a failed/cancelled payout's amount to the available balance."""
        self.pending_payout -= amount_cents
        self.available_balance += amount_cents
        self.save()
    
    @property
    def available_balance_dollars(self):
        return self.available_balance / 100
    
    @property
    def pending_payout_dollars(self):
        return self.pending_payout / 100
    
    @property
    def total_earnings_dollars(self):
        return self.total_earnings / 100

    @property
    def total_payouts_dollars(self):
        return self.total_payouts / 100


# ──────────────────────────────────────────────────────────────────
# PAYOUT MODEL
# ──────────────────────────────────────────────────────────────────

class PayoutStatus(models.TextChoices):
    """Payout states."""
    SCHEDULED = 'scheduled', _('Scheduled')
    PROCESSING = 'processing', _('Processing')
    PAID = 'paid', _('Paid')
    FAILED = 'failed', _('Failed')


class Payout(models.Model):
    """Seller payout batch (monthly or on-demand)."""
    
    # Reference
    payout_id = models.CharField(max_length=20, unique=True)
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT, related_name='payouts')
    
    # Amount (in cents)
    amount_cents = models.BigIntegerField()
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=PayoutStatus.choices,
        default=PayoutStatus.SCHEDULED,
    )
    
    # Bank Details
    bank_name = models.CharField(max_length=255, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
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
        return f"{self.payout_id} - {self.seller.user.username} - ${self.amount_dollars:.2f}"
    
    def save(self, *args, **kwargs):
        # Auto-generate payout ID
        if not self.payout_id:
            date_str = timezone.now().strftime('%Y%m%d')
            count = Payout.objects.filter(payout_id__startswith=f'PAY-{date_str}').count()
            self.payout_id = f'PAY-{date_str}-{count + 1:03d}'
        super().save(*args, **kwargs)
    
    @property
    def amount_dollars(self):
        return self.amount_cents / 100


# ──────────────────────────────────────────────────────────────────
# DISPUTE MODEL (Buyer Protection)
# ──────────────────────────────────────────────────────────────────

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


class DisputeReason(models.TextChoices):
    """Why the buyer is opening a dispute."""
    NOT_RECEIVED = 'not_received', _('Item Not Received')
    DAMAGED = 'damaged', _('Item Damaged')
    NOT_AS_DESCRIBED = 'not_as_described', _('Item Not as Described')
    WRONG_ITEM = 'wrong_item', _('Wrong Item Received')
    OTHER = 'other', _('Other')


class Dispute(models.Model):
    """Buyer-initiated dispute (damaged, non-delivery, etc.)."""
    
    # Reference
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name='dispute')
    dispute_id = models.CharField(max_length=20, unique=True)
    
    # Participants
    buyer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='disputes_initiated')
    seller = models.ForeignKey('olretail.Seller', on_delete=models.PROTECT, related_name='disputes_received')
    
    # Content
    reason = models.CharField(max_length=100, choices=DisputeReason.choices)
    description = models.TextField()
    
    # Evidence
    buyer_evidence = models.TextField(blank=True)
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
    seller_response_deadline = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Admin
    admin_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='disputes_resolved'
    )
    
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
            date_str = timezone.now().strftime('%Y%m%d')
            count = Dispute.objects.filter(dispute_id__startswith=f'DIS-{date_str}').count()
            self.dispute_id = f'DIS-{date_str}-{count + 1:03d}'
        
        if not self.seller_response_deadline:
            from datetime import timedelta
            self.seller_response_deadline = timezone.now() + timedelta(days=3)

        super().save(*args, **kwargs)


# ──────────────────────────────────────────────────────────────────
# PLATFORM SETTINGS (singleton, admin-editable)
# ──────────────────────────────────────────────────────────────────

class PlatformSettings(models.Model):
    """Single row of platform-level config editable from the admin
    dashboard — currently just where sellers send subscription payments
    (falls back to settings.PLATFORM_PAYMENT_INSTRUCTIONS until set)."""

    payment_instructions = models.TextField(
        blank=True,
        help_text=_(
            "Bank or mobile money details shown to sellers when they pay the "
            "platform for a subscription upgrade."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Platform settings'

    def __str__(self):
        return 'Platform settings'

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj
