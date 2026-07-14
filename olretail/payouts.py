"""Seller payout batching.

Payouts are money movements the platform still does by hand (bank transfer) —
see HANDOFF.md. This module only decides *who is owed a payout* and records
that as a `Payout` row; marking it paid/failed and actually moving the money
is an admin action in the dashboard (`dashboard/views.py`).
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .payment_models import Payout, SellerBalance


def create_scheduled_payouts():
    """Create a Payout for every seller whose available balance has cleared
    their minimum payout threshold, moving that amount from available to
    pending. Returns the list of created Payout instances."""
    today = timezone.localdate()
    eligible = SellerBalance.objects.select_related("seller__user").filter(
        available_balance__gt=0, available_balance__gte=F("min_payout_cents")
    )

    created = []
    for balance in eligible:
        with transaction.atomic():
            amount = balance.available_balance
            payout = Payout.objects.create(
                seller=balance.seller,
                amount_cents=amount,
                scheduled_date=today,
            )
            balance.schedule_payout(amount)
        created.append(payout)
    return created
