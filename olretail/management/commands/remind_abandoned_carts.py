from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.translation import gettext as _

from olretail.payment_models import Cart
from olretail.payment_views import _notify


class Command(BaseCommand):
    help = (
        "Notify (in-app + email) buyers whose cart items have sat untouched for a while "
        "and haven't already been reminded — meant to run on a daily schedule."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=24,
            help="How old a cart item must be before it counts as abandoned (default 24).",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["hours"])
        items = list(
            Cart.objects.filter(added_at__lte=cutoff, abandoned_reminder_sent_at__isnull=True)
            .select_related("buyer", "product")
        )

        if not items:
            self.stdout.write("No abandoned carts to remind.")
            return

        by_buyer = {}
        for item in items:
            by_buyer.setdefault(item.buyer, []).append(item)

        for buyer, cart_items in by_buyer.items():
            names = ", ".join(i.product.name for i in cart_items[:5])
            extra = len(cart_items) - 5
            if extra > 0:
                names += _(" and %(count)d more") % {"count": extra}
            message = _(
                "You still have items in your cart: %(items)s. Complete your purchase before they sell out!"
            ) % {"items": names}
            _notify(buyer, message)
            Cart.objects.filter(id__in=[i.id for i in cart_items]).update(
                abandoned_reminder_sent_at=timezone.now()
            )

        self.stdout.write(self.style.SUCCESS(
            f"Reminded {len(by_buyer)} buyer(s) about {len(items)} abandoned cart item(s)."
        ))
