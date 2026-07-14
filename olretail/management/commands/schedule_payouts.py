from django.core.management.base import BaseCommand

from olretail.payouts import create_scheduled_payouts


class Command(BaseCommand):
    help = "Create Payout records for sellers whose available balance has cleared their payout threshold."

    def handle(self, *args, **options):
        payouts = create_scheduled_payouts()
        if not payouts:
            self.stdout.write("No sellers are currently eligible for a payout.")
            return

        total = sum(p.amount_cents for p in payouts) / 100
        self.stdout.write(self.style.SUCCESS(
            f"Scheduled {len(payouts)} payout(s) totaling ${total:.2f}."
        ))
        for p in payouts:
            self.stdout.write(f"  {p.payout_id} — {p.seller.user.username} — ${p.amount_dollars:.2f}")
