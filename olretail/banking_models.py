from django.db import models
from django.utils.translation import gettext_lazy as _


# ──────────────────────────────────────────────────────────────────
# SIMULATED BANK GATEWAY — dev/test environment for automated bank
# transfers, built so a real bank API can later implement the same
# PaymentGateway interface (see olretail/payment_gateways.py) without any
# changes to the models or business logic below.
# ──────────────────────────────────────────────────────────────────

class VirtualAccountStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    CLOSED = 'closed', _('Closed')
    FROZEN = 'frozen', _('Frozen')


class ForcedOutcome(models.TextChoices):
    """Lets a named test account deterministically reproduce one scenario
    regardless of amount/balance — tests need repeatable outcomes, not
    randomness."""
    AUTO = 'auto', _('Automatic (balance-based)')
    ALWAYS_SUCCESS = 'always_success', _('Always Succeed')
    ALWAYS_FAIL = 'always_fail', _('Always Fail')
    ALWAYS_TIMEOUT = 'always_timeout', _('Always Timeout')
    ALWAYS_INSUFFICIENT_FUNDS = 'always_insufficient_funds', _('Always Insufficient Funds')
    ALWAYS_DUPLICATE = 'always_duplicate', _('Always Flag as Duplicate')


class VirtualBankAccount(models.Model):
    """Admin-managed test fixture — not a real balance ledger. Buyers pick
    one of these by account number at checkout to deterministically trigger
    a payment scenario; the platform's Order/Payment/Transaction/
    SellerBalance records the actual transaction, same as Stripe does."""

    account_number = models.CharField(max_length=34, unique=True)
    account_holder_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255, default='TimorMart Simulated Bank')
    balance_cents = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=10, choices=VirtualAccountStatus.choices, default=VirtualAccountStatus.ACTIVE,
    )
    forced_outcome = models.CharField(
        max_length=30, choices=ForcedOutcome.choices, default=ForcedOutcome.AUTO,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['account_number']

    def __str__(self):
        return f"{self.account_number} — {self.account_holder_name}"

    @property
    def balance_dollars(self):
        return self.balance_cents / 100


class SimulatedOutcome(models.TextChoices):
    PENDING = 'pending', _('Pending')
    SUCCESS = 'success', _('Success')
    FAILED = 'failed', _('Failed')
    CANCELLED = 'cancelled', _('Cancelled')
    TIMEOUT = 'timeout', _('Timeout')
    INSUFFICIENT_FUNDS = 'insufficient_funds', _('Insufficient Funds')
    INVALID_ACCOUNT = 'invalid_account', _('Invalid / Closed Account')
    DUPLICATE = 'duplicate', _('Duplicate Transaction')


class SimulatedBankTransaction(models.Model):
    """One row per Payment made via the simulated gateway — the
    gateway-specific state machine. Payment itself stays gateway-agnostic
    (see gateway/gateway_reference on Payment)."""

    payment = models.OneToOneField(
        'olretail.Payment', on_delete=models.CASCADE, related_name='bank_simulation',
    )
    reference = models.CharField(max_length=40, unique=True)

    # Raw input is kept even when it doesn't resolve to a real account, so an
    # invalid-account attempt still shows up in payment history.
    account_number_submitted = models.CharField(max_length=34)
    source_account = models.ForeignKey(
        VirtualBankAccount, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions',
    )

    amount_cents = models.BigIntegerField()

    # Current/visible state.
    status = models.CharField(
        max_length=20, choices=SimulatedOutcome.choices, default=SimulatedOutcome.PENDING,
    )
    # Decided at initiate() time, applied to `status` at settlement — lets
    # tests assert the eventual outcome without waiting for it to land.
    pending_outcome = models.CharField(max_length=20, choices=SimulatedOutcome.choices, blank=True)

    attempt_count = models.PositiveIntegerField(default=1)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    # Null = never auto-settles (the ALWAYS_TIMEOUT fixture) — only the
    # sweep command or an admin moves it forward.
    settle_after = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.reference} - {self.status}"

    @property
    def amount_dollars(self):
        return self.amount_cents / 100


class GatewayEventLog(models.Model):
    """Detailed request/response log — backs the 'view complete payment
    logs' and 'replay webhook callbacks' admin features."""

    DIRECTION_CHOICES = [('outbound', _('Outbound')), ('inbound', _('Inbound'))]

    transaction = models.ForeignKey(
        SimulatedBankTransaction, on_delete=models.CASCADE, related_name='event_logs',
    )
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    event_type = models.CharField(max_length=50)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction.reference} {self.direction}/{self.event_type}"


class IdempotencyRecord(models.Model):
    """Client-safety net for the developer REST API: a repeated POST with
    the same Idempotency-Key returns the original response instead of
    creating a second transaction. Separate from SimulatedOutcome.DUPLICATE
    above, which is a simulated bank-side fraud outcome, not a client-retry
    safety mechanism."""

    key = models.CharField(max_length=255, unique=True)
    endpoint = models.CharField(max_length=100)
    request_fingerprint = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key
