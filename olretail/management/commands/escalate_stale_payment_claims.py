from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.translation import gettext as _

from olretail.payment_models import Dispute, DisputeReason, DisputeStatus, Order, OrderStatus, PaymentMethod
from olretail.payment_views import _notify


class Command(BaseCommand):
    """A seller who simply never clicks confirm *or* deny leaves a buyer
    with no recourse — this closes that gap by auto-escalating a
    bank-transfer order to admin review once it's sat in Payment Reported
    too long with no response either way. Meant to run daily; see
    PAYMENT_VERIFICATION.md for the full payment-dispute design."""

    help = (
        "Escalate bank-transfer orders whose seller hasn't confirmed or denied a "
        "reported payment within the response window, so they don't sit unresolved forever."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=3,
            help="How long a seller has to confirm/deny before this counts as no response (default 3).",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale_orders = (
            Order.objects.filter(
                payment_method=PaymentMethod.BANK_TRANSFER,
                status=OrderStatus.PAYMENT_REPORTED,
                payment_reported_at__lte=cutoff,
            )
            .exclude(disputes__status__in=[DisputeStatus.OPEN, DisputeStatus.SELLER_RESPONSE, DisputeStatus.UNDER_REVIEW])
            .select_related("buyer", "seller__user")
        )

        count = 0
        for order in stale_orders:
            Dispute.objects.create(
                order=order,
                buyer=order.buyer,
                seller=order.seller,
                reason=DisputeReason.PAYMENT_NO_RESPONSE,
                description=(
                    _("Buyer claims payment sent for order %(order)s; seller did not confirm or "
                      "deny receipt within %(days)d day(s).")
                    % {"order": order.order_number, "days": options["days"]}
                ),
                status=DisputeStatus.UNDER_REVIEW,
            )
            _notify(
                order.buyer,
                _("Your seller hasn't responded to your payment for order %(order)s — "
                  "an administrator is now reviewing it.") % {"order": order.order_number},
                order=order,
            )
            _notify(
                order.seller.user,
                _("You didn't confirm or deny the buyer's payment for order %(order)s in time — "
                  "an administrator is now reviewing it.") % {"order": order.order_number},
                order=order,
            )
            count += 1

        if count:
            self.stdout.write(self.style.SUCCESS(f"Escalated {count} stale payment claim(s) to admin review."))
        else:
            self.stdout.write("No stale payment claims to escalate.")
