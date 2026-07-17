"""Payment gateway abstraction.

PaymentGateway is the interface any payment backend implements — today only
SimulatedBankGateway exists, but a real bank API can implement the same
interface later without touching payment_views.py's business logic (order
status, commission, SellerBalance, notifications all stay in
_mark_payment_succeeded/_mark_payment_failed, which are gateway-agnostic).

Stripe is intentionally NOT retrofitted onto this interface — that would be
a separate, larger refactor of already-working code and isn't needed for
the simulated bank gateway to work.
"""

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .banking_models import (
    ForcedOutcome, GatewayEventLog, SimulatedBankTransaction, SimulatedOutcome,
    VirtualAccountStatus, VirtualBankAccount,
)

logger = logging.getLogger(__name__)


class PaymentGatewayResult:
    """Normalized result returned by every PaymentGateway method."""

    def __init__(self, outcome, reference='', message=''):
        self.outcome = outcome
        self.reference = reference
        self.message = message


class PaymentGateway:
    """Interface a real bank/card gateway would implement."""

    def initiate(self, payment, **kwargs):
        raise NotImplementedError

    def get_status(self, payment):
        raise NotImplementedError

    def cancel(self, payment):
        raise NotImplementedError

    def refund(self, payment, amount_cents=None):
        raise NotImplementedError


def _generate_reference():
    """SIMBANK-YYYYMMDD-NNNN, same retry-on-collision pattern as
    Order.order_number (see payment_models.Order.save)."""
    for _attempt in range(5):
        date_str = timezone.now().strftime('%Y%m%d')
        last = (
            SimulatedBankTransaction.objects.filter(reference__startswith=f'SIMBANK-{date_str}-')
            .order_by('-reference')
            .values_list('reference', flat=True)
            .first()
        )
        last_seq = int(last.rsplit('-', 1)[-1]) if last else 0
        candidate = f'SIMBANK-{date_str}-{last_seq + 1:04d}'
        if not SimulatedBankTransaction.objects.filter(reference=candidate).exists():
            return candidate
    raise RuntimeError('Could not generate a unique simulated bank transaction reference')


def _resolve_outcome(account, amount_cents):
    """Deterministic outcome for an ACTIVE account — driven by
    forced_outcome/balance, never randomness, so tests are repeatable."""
    forced = {
        ForcedOutcome.ALWAYS_SUCCESS: SimulatedOutcome.SUCCESS,
        ForcedOutcome.ALWAYS_FAIL: SimulatedOutcome.FAILED,
        ForcedOutcome.ALWAYS_TIMEOUT: SimulatedOutcome.TIMEOUT,
        ForcedOutcome.ALWAYS_INSUFFICIENT_FUNDS: SimulatedOutcome.INSUFFICIENT_FUNDS,
        ForcedOutcome.ALWAYS_DUPLICATE: SimulatedOutcome.DUPLICATE,
    }.get(account.forced_outcome)
    if forced:
        return forced
    return SimulatedOutcome.INSUFFICIENT_FUNDS if amount_cents > account.balance_cents else SimulatedOutcome.SUCCESS


def _is_likely_duplicate(account, amount_cents):
    """Secondary realism check on top of the ALWAYS_DUPLICATE fixture (the
    reliable/testable path): same account+amount submitted again within the
    last minute."""
    window_start = timezone.now() - timedelta(seconds=60)
    return SimulatedBankTransaction.objects.filter(
        source_account=account, amount_cents=amount_cents, created_at__gte=window_start,
    ).exists()


def _settle_delay():
    return timezone.now() + timedelta(seconds=settings.SIMULATED_BANK_SETTLE_DELAY_SECONDS)


class SimulatedBankGateway(PaymentGateway):
    """Fake bank that mimics a real bank API closely enough to exercise the
    full payment lifecycle — pending -> settled, webhook callback, retries,
    refunds — without a real banking partner."""

    def initiate(self, payment, *, account_number, amount_cents, order_reference):
        account = VirtualBankAccount.objects.filter(account_number=account_number).first()

        if account is None or account.status != VirtualAccountStatus.ACTIVE:
            return self._reject_immediately(
                payment, account=None, account_number_submitted=account_number,
                amount_cents=amount_cents, outcome=SimulatedOutcome.INVALID_ACCOUNT,
                message=str(_('No active account found for that account number.')),
            )

        if account.forced_outcome == ForcedOutcome.ALWAYS_DUPLICATE or _is_likely_duplicate(account, amount_cents):
            return self._reject_immediately(
                payment, account=account, account_number_submitted=account_number,
                amount_cents=amount_cents, outcome=SimulatedOutcome.DUPLICATE,
                message=str(_('A matching transaction was already submitted recently.')),
            )

        outcome = _resolve_outcome(account, amount_cents)
        is_timeout = outcome == SimulatedOutcome.TIMEOUT
        reference = _generate_reference()

        txn = SimulatedBankTransaction.objects.create(
            payment=payment,
            reference=reference,
            account_number_submitted=account_number,
            source_account=account,
            amount_cents=amount_cents,
            status=SimulatedOutcome.PENDING,
            pending_outcome=outcome,
            settle_after=None if is_timeout else _settle_delay(),
        )
        payment.gateway_reference = reference
        payment.save(update_fields=['gateway_reference'])

        GatewayEventLog.objects.create(
            transaction=txn, direction='outbound', event_type='initiate',
            request_payload={
                'account_number': account_number, 'amount_cents': amount_cents,
                'order_reference': order_reference,
            },
            response_payload={'reference': reference, 'status': SimulatedOutcome.PENDING},
            status_code=202,
        )

        if not is_timeout:
            db_transaction.on_commit(lambda: _schedule_settlement(txn.id))

        return PaymentGatewayResult(outcome=SimulatedOutcome.PENDING, reference=reference)

    def _reject_immediately(self, payment, *, account, account_number_submitted, amount_cents, outcome, message):
        """INVALID_ACCOUNT / DUPLICATE — a real bank rejects these
        instantly, no settlement delay needed. Still fully logged, so it
        shows up in payment history even though nothing was ever pending."""
        reference = _generate_reference()
        now = timezone.now()
        txn = SimulatedBankTransaction.objects.create(
            payment=payment,
            reference=reference,
            account_number_submitted=account_number_submitted,
            source_account=account,
            amount_cents=amount_cents,
            status=outcome,
            pending_outcome=outcome,
            error_message=message,
            settle_after=now,
            settled_at=now,
        )
        payment.gateway_reference = reference
        payment.save(update_fields=['gateway_reference'])
        GatewayEventLog.objects.create(
            transaction=txn, direction='outbound', event_type='initiate',
            request_payload={'account_number': account_number_submitted, 'amount_cents': amount_cents},
            response_payload={'reference': reference, 'status': outcome, 'message': message},
            status_code=402,
        )
        return PaymentGatewayResult(outcome=outcome, reference=reference, message=message)

    def get_status(self, payment):
        txn = getattr(payment, 'bank_simulation', None)
        if txn is None:
            return PaymentGatewayResult(outcome=SimulatedOutcome.FAILED, message=str(_('No transaction found.')))
        return PaymentGatewayResult(outcome=txn.status, reference=txn.reference)

    def cancel(self, payment):
        txn = getattr(payment, 'bank_simulation', None)
        if txn is None or txn.status != SimulatedOutcome.PENDING:
            return
        txn.status = SimulatedOutcome.CANCELLED
        txn.settled_at = timezone.now()
        txn.save(update_fields=['status', 'settled_at'])
        GatewayEventLog.objects.create(
            transaction=txn, direction='outbound', event_type='cancel',
            response_payload={'status': SimulatedOutcome.CANCELLED}, status_code=200,
        )

    def retry(self, payment):
        """Re-run the outcome decision against the same submitted account
        number — lets an admin fix the underlying account (top up balance,
        change forced_outcome) and retry without the buyer re-checking out."""
        txn = getattr(payment, 'bank_simulation', None)
        if txn is None:
            return PaymentGatewayResult(outcome=SimulatedOutcome.FAILED, message=str(_('No transaction to retry.')))

        account = VirtualBankAccount.objects.filter(account_number=txn.account_number_submitted).first()
        if account is None or account.status != VirtualAccountStatus.ACTIVE:
            outcome = SimulatedOutcome.INVALID_ACCOUNT
        else:
            outcome = _resolve_outcome(account, txn.amount_cents)

        txn.source_account = account
        txn.attempt_count += 1
        txn.error_message = ''
        is_timeout = outcome == SimulatedOutcome.TIMEOUT
        is_immediate_reject = outcome in (SimulatedOutcome.INVALID_ACCOUNT, SimulatedOutcome.DUPLICATE)

        if is_immediate_reject:
            txn.status = outcome
            txn.pending_outcome = outcome
            txn.settle_after = timezone.now()
            txn.settled_at = timezone.now()
        else:
            txn.status = SimulatedOutcome.PENDING
            txn.pending_outcome = outcome
            txn.settle_after = None if is_timeout else _settle_delay()
            txn.settled_at = None
        txn.save()

        # A previous attempt may have already applied _mark_payment_failed
        # (Payment.status=FAILED), which would make _process_bank_callback's
        # "already applied" guard wrongly skip this attempt's outcome once it
        # settles. Reset it back to PENDING so the retry gets a clean shot —
        # only meaningful when the previous attempt actually failed, a
        # succeeded payment can't be retried in the first place (see
        # payment_views._process_bank_refund for reversing a success instead).
        from .payment_models import PaymentStatus  # local import: avoid a module-load cycle
        if payment.status == PaymentStatus.FAILED:
            payment.status = PaymentStatus.PENDING
            payment.error_message = ''
            payment.save(update_fields=['status', 'error_message'])

        GatewayEventLog.objects.create(
            transaction=txn, direction='outbound', event_type='retry',
            response_payload={'status': txn.status, 'attempt': txn.attempt_count}, status_code=202,
        )

        if txn.status == SimulatedOutcome.PENDING:
            if not is_timeout:
                db_transaction.on_commit(lambda: _schedule_settlement(txn.id))
        else:
            db_transaction.on_commit(lambda: _settle_simulated_transaction(txn.id))

        return PaymentGatewayResult(outcome=txn.status, reference=txn.reference)

    def refund(self, payment, amount_cents=None):
        """Bank-side effect only (credit the virtual account back) — Order/
        Payment/SellerBalance reversal is business logic that lives in
        payment_views._process_bank_refund, which calls this."""
        txn = getattr(payment, 'bank_simulation', None)
        if txn is None or txn.status != SimulatedOutcome.SUCCESS:
            raise ValueError('Only a settled, successful simulated-bank transaction can be refunded.')

        refund_amount = amount_cents or txn.amount_cents
        if txn.source_account:
            txn.source_account.balance_cents += refund_amount
            txn.source_account.save(update_fields=['balance_cents'])

        GatewayEventLog.objects.create(
            transaction=txn, direction='outbound', event_type='refund',
            request_payload={'amount_cents': refund_amount},
            response_payload={'status': 'refunded'}, status_code=200,
        )
        return PaymentGatewayResult(outcome='refunded', reference=txn.reference)


def _schedule_settlement(transaction_id):
    """Best-effort auto-settle via a background timer — a nicer
    interactive-testing UX, NOT the mechanism relied on for correctness (it
    dies on runserver autoreload and doesn't survive a process restart).
    Reconcile-on-access (_reconcile_payment) and the
    settle_simulated_bank_transactions sweep command are the reliable
    paths — see BANK_SIMULATOR_ARCHITECTURE.md."""
    try:
        txn = SimulatedBankTransaction.objects.get(id=transaction_id)
    except SimulatedBankTransaction.DoesNotExist:
        return
    if txn.settle_after is None:
        return
    delay = max((txn.settle_after - timezone.now()).total_seconds(), 0)
    timer = threading.Timer(delay, _settle_simulated_transaction, args=[transaction_id])
    timer.daemon = True
    timer.start()


def _settle_simulated_transaction(transaction_id):
    """Idempotent/re-entrant-safe — callable from the Timer, the sweep
    command, and the admin 'Settle now' action without risk of double-
    applying side effects. Mirrors the `if payment.status != SUCCEEDED:
    return` guard already used in stripe_webhook."""
    with db_transaction.atomic():
        try:
            txn = SimulatedBankTransaction.objects.select_for_update().get(id=transaction_id)
        except SimulatedBankTransaction.DoesNotExist:
            return
        if txn.status != SimulatedOutcome.PENDING:
            return

        txn.status = txn.pending_outcome or SimulatedOutcome.FAILED
        txn.settled_at = timezone.now()
        if txn.status != SimulatedOutcome.SUCCESS and not txn.error_message:
            txn.error_message = f'Simulated outcome: {txn.get_status_display()}'
        txn.save()

        if txn.status == SimulatedOutcome.SUCCESS and txn.source_account:
            txn.source_account.balance_cents -= txn.amount_cents
            txn.source_account.save(update_fields=['balance_cents'])

        GatewayEventLog.objects.create(
            transaction=txn, direction='inbound', event_type='callback',
            response_payload={'status': txn.status}, status_code=200,
        )

    # Delivered outside the row lock, same shape a real inbound webhook
    # would take — payment_views owns what "succeeded"/"failed" means for
    # Order/SellerBalance/notifications, not this module.
    from . import payment_views  # local import: avoid a module-load cycle
    payment_views._process_bank_callback(txn, source='simulated_settlement')


def sweep_pending_transactions():
    """Called by the settle_simulated_bank_transactions management command
    (and usable from tests instead of sleeping): settles any PENDING
    transaction past its settle_after, and separately flags any PENDING
    transaction with settle_after=None (the ALWAYS_TIMEOUT fixture) that's
    sat unresolved longer than SIMULATED_BANK_TIMEOUT_SECONDS as TIMEOUT.
    Returns (settled_count, timed_out_count)."""
    due_ids = list(
        SimulatedBankTransaction.objects.filter(
            status=SimulatedOutcome.PENDING, settle_after__isnull=False, settle_after__lte=timezone.now(),
        ).values_list('id', flat=True)
    )
    for txn_id in due_ids:
        _settle_simulated_transaction(txn_id)

    timeout_cutoff = timezone.now() - timedelta(seconds=settings.SIMULATED_BANK_TIMEOUT_SECONDS)
    overdue_timeouts = SimulatedBankTransaction.objects.filter(
        status=SimulatedOutcome.PENDING, settle_after__isnull=True, created_at__lte=timeout_cutoff,
    )
    timed_out_count = 0
    for txn in overdue_timeouts:
        with db_transaction.atomic():
            txn = SimulatedBankTransaction.objects.select_for_update().get(id=txn.id)
            if txn.status != SimulatedOutcome.PENDING:
                continue
            txn.status = SimulatedOutcome.TIMEOUT
            txn.pending_outcome = SimulatedOutcome.TIMEOUT
            txn.settled_at = timezone.now()
            txn.error_message = txn.error_message or 'Simulated bank did not respond in time.'
            txn.save()
            GatewayEventLog.objects.create(
                transaction=txn, direction='inbound', event_type='timeout',
                response_payload={'status': SimulatedOutcome.TIMEOUT}, status_code=504,
            )
        from . import payment_views  # local import: avoid a module-load cycle
        payment_views._process_bank_callback(txn, source='sweep_timeout')
        timed_out_count += 1

    return len(due_ids), timed_out_count
