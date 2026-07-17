from django.core.management.base import BaseCommand

from olretail.banking_models import ForcedOutcome, VirtualAccountStatus, VirtualBankAccount

# (account_number, holder name, forced_outcome, status, balance_cents, notes)
FIXTURE_ACCOUNTS = [
    (
        'SIM-0001-SUCCESS', 'Test — Always Succeeds',
        ForcedOutcome.ALWAYS_SUCCESS, VirtualAccountStatus.ACTIVE, 1_000_000,
        'Seeded fixture — every payment against this account succeeds.',
    ),
    (
        'SIM-0002-INSUFFICIENT', 'Test — Insufficient Funds',
        ForcedOutcome.ALWAYS_INSUFFICIENT_FUNDS, VirtualAccountStatus.ACTIVE, 100,
        'Seeded fixture — every payment against this account is declined for insufficient funds.',
    ),
    (
        'SIM-0003-CLOSED', 'Test — Closed / Invalid Account',
        ForcedOutcome.AUTO, VirtualAccountStatus.CLOSED, 0,
        'Seeded fixture — a closed account, so any payment against it is rejected as invalid.',
    ),
    (
        'SIM-0004-FAIL', 'Test — Always Fails',
        ForcedOutcome.ALWAYS_FAIL, VirtualAccountStatus.ACTIVE, 1_000_000,
        'Seeded fixture — every payment against this account fails (generic decline).',
    ),
    (
        'SIM-0005-TIMEOUT', 'Test — Always Times Out',
        ForcedOutcome.ALWAYS_TIMEOUT, VirtualAccountStatus.ACTIVE, 1_000_000,
        'Seeded fixture — payments against this account never auto-settle; use "Retry" or '
        'the sweep command to move it forward.',
    ),
    (
        'SIM-0006-DUPLICATE', 'Test — Always Flags Duplicate',
        ForcedOutcome.ALWAYS_DUPLICATE, VirtualAccountStatus.ACTIVE, 1_000_000,
        'Seeded fixture — every payment against this account is flagged as a duplicate transaction.',
    ),
]


class Command(BaseCommand):
    help = (
        "Create/reset the 6 named virtual bank accounts used to deterministically "
        "trigger each simulated payment outcome at checkout."
    )

    def handle(self, *args, **options):
        created, updated = 0, 0
        for account_number, name, forced_outcome, status, balance_cents, notes in FIXTURE_ACCOUNTS:
            account, was_created = VirtualBankAccount.objects.update_or_create(
                account_number=account_number,
                defaults={
                    'account_holder_name': name,
                    'forced_outcome': forced_outcome,
                    'status': status,
                    'balance_cents': balance_cents,
                    'notes': notes,
                },
            )
            created += was_created
            updated += not was_created

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(FIXTURE_ACCOUNTS)} test account(s): {created} created, {updated} reset to defaults."
        ))
        for account_number, name, *_rest in FIXTURE_ACCOUNTS:
            self.stdout.write(f"  {account_number} — {name}")
