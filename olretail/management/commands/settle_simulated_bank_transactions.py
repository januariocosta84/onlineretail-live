from django.core.management.base import BaseCommand

from olretail.payment_gateways import sweep_pending_transactions


class Command(BaseCommand):
    help = (
        "Settle any simulated-bank transaction past its settle_after time, and flag "
        "any overdue 'always timeout' transaction as TIMEOUT. This is the reliable "
        "settlement path — the in-process threading.Timer is best-effort only."
    )

    def handle(self, *args, **options):
        settled_count, timed_out_count = sweep_pending_transactions()
        if not settled_count and not timed_out_count:
            self.stdout.write("Nothing to settle.")
            return
        self.stdout.write(self.style.SUCCESS(
            f"Settled {settled_count} transaction(s), flagged {timed_out_count} as timed out."
        ))
