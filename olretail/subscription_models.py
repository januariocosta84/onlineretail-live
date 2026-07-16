"""Seller listing limits and paid upgrades.

Free sellers may list up to FREE_PRODUCT_LIMIT products. Posting more
requires an active paid plan. There's no automated billing — a seller pays
the platform directly (bank/mobile transfer) and reports it here
(SubscriptionRequest); an admin confirms the payment was received before it
activates (SellerSubscription), the same "subject to the admin" pattern
already used for bank-transfer orders and payouts.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

FREE_PRODUCT_LIMIT = 10
EXPIRY_WARNING_DAYS = 5  # start nudging the seller to renew this many days out


class SubscriptionPlan(models.TextChoices):
    FREE = 'free', _('Free')
    MONTHLY = 'monthly', _('Monthly — $11/month')
    YEARLY = 'yearly', _('Yearly — $100/year')


PLAN_PRICES = {
    SubscriptionPlan.MONTHLY: Decimal('11.00'),
    SubscriptionPlan.YEARLY: Decimal('100.00'),
}
PLAN_DURATION_DAYS = {
    SubscriptionPlan.MONTHLY: 30,
    SubscriptionPlan.YEARLY: 365,
}


class SellerSubscription(models.Model):
    """A seller's current listing entitlement (one row per seller)."""

    seller = models.OneToOneField('olretail.Seller', on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=10, choices=SubscriptionPlan.choices, default=SubscriptionPlan.FREE)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.seller.get_name} — {self.get_plan_display()}"

    @property
    def is_paid_active(self):
        return (
            self.plan != SubscriptionPlan.FREE
            and self.expires_at is not None
            and self.expires_at > timezone.now()
        )

    @property
    def products_used(self):
        return self.seller.product_set.count()

    @property
    def remaining_free_slots(self):
        return max(0, FREE_PRODUCT_LIMIT - self.products_used)

    @property
    def is_over_free_limit(self):
        return self.products_used > FREE_PRODUCT_LIMIT

    @property
    def days_until_expiry(self):
        if not self.expires_at:
            return None
        return max(0, (self.expires_at - timezone.now()).days)

    @property
    def expiring_soon(self):
        """Still active, but the renewal window is closing — nudge the
        seller before they lose the ability to post new products."""
        return (
            self.is_paid_active
            and self.is_over_free_limit
            and self.days_until_expiry is not None
            and self.days_until_expiry <= EXPIRY_WARNING_DAYS
        )

    @property
    def needs_renewal(self):
        """Plan lapsed and the seller has more listings than the free tier
        allows: existing listings stay live, but they can't post new ones
        until they renew."""
        return not self.is_paid_active and self.is_over_free_limit

    def can_post_product(self):
        return self.is_paid_active or self.products_used < FREE_PRODUCT_LIMIT

    def compute_renewal(self, plan, reference_date):
        """The single source of truth for "extend vs. start fresh," used by
        both the admin approval action and any preview UI, so the two can
        never disagree.

        `reference_date` must be when the seller actually paid/reported the
        renewal (`SubscriptionRequest.created_at`) — NOT `timezone.now()`.
        Admin approval can lag behind submission by days; anchoring on "now"
        would silently strip a seller of an extension they're entitled to
        if their old period expires while the request is still sitting in
        the queue. Returns (new_expires_at, extended: bool).
        """
        still_active = (
            self.expires_at is not None
            and self.plan != SubscriptionPlan.FREE
            and self.expires_at > reference_date
        )
        base = self.expires_at if still_active else reference_date
        return base + timedelta(days=PLAN_DURATION_DAYS[plan]), still_active


class SubscriptionRequestStatus(models.TextChoices):
    PENDING = 'pending', _('Payment Reported — Awaiting Confirmation')
    APPROVED = 'approved', _('Approved')
    REJECTED = 'rejected', _('Rejected')


class SubscriptionRequest(models.Model):
    """One seller's report of having paid for a plan upgrade, awaiting
    admin confirmation."""

    seller = models.ForeignKey('olretail.Seller', on_delete=models.CASCADE, related_name='subscription_requests')
    plan = models.CharField(
        max_length=10,
        choices=[(SubscriptionPlan.MONTHLY, SubscriptionPlan.MONTHLY.label),
                 (SubscriptionPlan.YEARLY, SubscriptionPlan.YEARLY.label)],
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    payment_reference = models.TextField(
        help_text=_("How/when you paid — e.g. bank transfer reference, mobile money confirmation.")
    )
    status = models.CharField(
        max_length=10, choices=SubscriptionRequestStatus.choices, default=SubscriptionRequestStatus.PENDING
    )
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.seller.get_name} — {self.get_plan_display()} ({self.status})"
