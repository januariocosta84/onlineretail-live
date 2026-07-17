"""Admin UI for the simulated bank gateway — virtual test accounts and the
transactions run against them. Same list/detail/action + log_action
convention as payouts/courier verification in views.py."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from olretail.banking_models import (
    ForcedOutcome, GatewayEventLog, SimulatedBankTransaction, SimulatedOutcome,
    VirtualAccountStatus, VirtualBankAccount,
)
from olretail.payment_gateways import SimulatedBankGateway, _settle_simulated_transaction
from olretail.payment_views import _process_bank_callback, _process_bank_refund

from .decorators import admin_required
from .utils import log_action

PAGE_SIZE = 20


# ── Virtual bank accounts ───────────────────────────────────────────────

@admin_required
def bank_accounts(request):
    qs = VirtualBankAccount.objects.all()
    search = request.GET.get('q', '').strip()
    if search:
        qs = qs.filter(account_number__icontains=search) | qs.filter(account_holder_name__icontains=search)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/bank_accounts.html', {
        'section': 'bank_accounts',
        'page_obj': page_obj,
        'search': search,
        'status_choices': VirtualAccountStatus.choices,
        'forced_outcome_choices': ForcedOutcome.choices,
    })


@admin_required
@require_POST
def bank_account_create(request):
    account_number = request.POST.get('account_number', '').strip()
    account_holder_name = request.POST.get('account_holder_name', '').strip()
    if not account_number or not account_holder_name:
        messages.error(request, 'Account number and holder name are required.')
        return redirect('dashboard:bank_accounts')
    if VirtualBankAccount.objects.filter(account_number=account_number).exists():
        messages.error(request, f'Account number {account_number} already exists.')
        return redirect('dashboard:bank_accounts')

    try:
        balance_cents = int(float(request.POST.get('balance_dollars', '0') or 0) * 100)
    except ValueError:
        balance_cents = 0

    account = VirtualBankAccount.objects.create(
        account_number=account_number,
        account_holder_name=account_holder_name,
        bank_name=request.POST.get('bank_name', '').strip() or 'TimorMart Simulated Bank',
        balance_cents=balance_cents,
        forced_outcome=request.POST.get('forced_outcome') or ForcedOutcome.AUTO,
        notes=request.POST.get('notes', '').strip(),
    )
    log_action(request, 'bank_sim_account_created', account.account_number)
    messages.success(request, f'Virtual account {account.account_number} created.')
    return redirect('dashboard:bank_account_detail', pk=account.pk)


@admin_required
def bank_account_detail(request, pk):
    account = get_object_or_404(VirtualBankAccount, pk=pk)
    transactions = account.transactions.select_related('payment').order_by('-created_at')[:25]
    return render(request, 'dashboard/bank_account_detail.html', {
        'section': 'bank_accounts',
        'account': account,
        'transactions': transactions,
        'status_choices': VirtualAccountStatus.choices,
        'forced_outcome_choices': ForcedOutcome.choices,
    })


@admin_required
@require_POST
def bank_account_action(request, pk):
    account = get_object_or_404(VirtualBankAccount, pk=pk)
    action = request.POST.get('action')

    if action == 'adjust_balance':
        try:
            new_balance_cents = int(float(request.POST.get('balance_dollars', '0')) * 100)
        except ValueError:
            messages.error(request, 'Enter a valid dollar amount.')
            return redirect('dashboard:bank_account_detail', pk=account.pk)
        old = account.balance_cents
        account.balance_cents = new_balance_cents
        account.save(update_fields=['balance_cents'])
        log_action(
            request, 'bank_sim_balance_adjusted', account.account_number,
            f'${old / 100:.2f} -> ${new_balance_cents / 100:.2f}',
        )
        messages.success(request, f'Balance updated to ${new_balance_cents / 100:.2f}.')

    elif action == 'set_forced_outcome':
        outcome = request.POST.get('forced_outcome')
        if outcome not in ForcedOutcome.values:
            messages.error(request, 'Invalid outcome.')
            return redirect('dashboard:bank_account_detail', pk=account.pk)
        account.forced_outcome = outcome
        account.save(update_fields=['forced_outcome'])
        log_action(request, 'bank_sim_forced_outcome_set', account.account_number, outcome)
        messages.success(request, f'{account.account_number} will now: {account.get_forced_outcome_display()}.')

    elif action == 'toggle_status':
        new_status = request.POST.get('status')
        if new_status not in VirtualAccountStatus.values:
            messages.error(request, 'Invalid status.')
            return redirect('dashboard:bank_account_detail', pk=account.pk)
        account.status = new_status
        account.save(update_fields=['status'])
        log_action(request, 'bank_sim_account_status_set', account.account_number, new_status)
        messages.success(request, f'{account.account_number} is now {account.get_status_display()}.')

    else:
        messages.error(request, 'Unknown action.')

    return redirect('dashboard:bank_account_detail', pk=account.pk)


# ── Simulated bank transactions ─────────────────────────────────────────

@admin_required
def bank_transactions(request):
    qs = SimulatedBankTransaction.objects.select_related('source_account', 'payment').order_by('-created_at')
    status = request.GET.get('status') or ''
    if status:
        qs = qs.filter(status=status)
    account_number = request.GET.get('account') or ''
    if account_number:
        qs = qs.filter(account_number_submitted__icontains=account_number)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/bank_transactions.html', {
        'section': 'bank_transactions',
        'page_obj': page_obj,
        'status': status,
        'account_number': account_number,
        'status_choices': SimulatedOutcome.choices,
    })


@admin_required
def bank_transaction_detail(request, pk):
    txn = get_object_or_404(
        SimulatedBankTransaction.objects.select_related('source_account', 'payment'), pk=pk,
    )
    orders = txn.payment.orders.select_related('seller', 'buyer').all() if txn.payment_id else []
    event_logs = txn.event_logs.order_by('-created_at')
    return render(request, 'dashboard/bank_transaction_detail.html', {
        'section': 'bank_transactions',
        'txn': txn,
        'orders': orders,
        'event_logs': event_logs,
    })


@admin_required
@require_POST
def bank_transaction_action(request, pk):
    txn = get_object_or_404(SimulatedBankTransaction.objects.select_related('payment'), pk=pk)
    action = request.POST.get('action')
    gateway = SimulatedBankGateway()

    if action == 'retry':
        if txn.status == SimulatedOutcome.PENDING:
            messages.error(request, 'This transaction is still pending — nothing to retry yet.')
        else:
            result = gateway.retry(txn.payment)
            log_action(request, 'bank_sim_transaction_retried', txn.reference, f'attempt {txn.attempt_count + 1}')
            messages.success(request, f'Retried — new outcome: {result.outcome}.')

    elif action == 'settle_now':
        if txn.status != SimulatedOutcome.PENDING:
            messages.error(request, 'This transaction has already settled.')
        else:
            _settle_simulated_transaction(txn.id)
            log_action(request, 'bank_sim_transaction_settled_now', txn.reference)
            messages.success(request, 'Transaction settled.')

    elif action == 'replay_callback':
        txn.refresh_from_db()
        if txn.status == SimulatedOutcome.PENDING:
            messages.error(request, 'Nothing to replay — this transaction is still pending.')
        else:
            _process_bank_callback(txn, source='admin_replay')
            GatewayEventLog.objects.create(
                transaction=txn, direction='inbound', event_type='admin_replay',
                response_payload={'status': txn.status}, status_code=200,
            )
            log_action(request, 'bank_sim_callback_replayed', txn.reference)
            messages.success(request, 'Callback replayed.')

    elif action == 'mark_failed':
        if txn.status != SimulatedOutcome.PENDING:
            messages.error(request, 'Only a pending transaction can be force-failed.')
        else:
            txn.status = SimulatedOutcome.FAILED
            txn.pending_outcome = SimulatedOutcome.FAILED
            txn.error_message = 'Manually marked as failed by an administrator.'
            txn.settled_at = timezone.now()
            txn.save()
            GatewayEventLog.objects.create(
                transaction=txn, direction='inbound', event_type='admin_mark_failed',
                response_payload={'status': SimulatedOutcome.FAILED}, status_code=200,
            )
            _process_bank_callback(txn, source='admin_mark_failed')
            log_action(request, 'bank_sim_transaction_marked_failed', txn.reference)
            messages.success(request, 'Transaction marked as failed.')

    elif action == 'refund':
        try:
            _process_bank_refund(txn.payment)
            log_action(request, 'bank_sim_transaction_refunded', txn.reference)
            messages.success(request, 'Refund processed.')
        except ValueError as e:
            messages.error(request, str(e))

    else:
        messages.error(request, 'Unknown action.')

    return redirect('dashboard:bank_transaction_detail', pk=txn.pk)
