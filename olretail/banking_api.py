"""Developer REST API for the simulated bank gateway — plain Django views
(JsonResponse), matching the rest of this app's hand-rolled-webhook
convention rather than pulling in a DRF dependency. See
BANK_SIMULATOR_ARCHITECTURE.md for the full documented surface.

This API is independent of the marketplace checkout flow: checkout calls
SimulatedBankGateway directly (see payment_views._process_simulated_bank_checkout),
it doesn't loop back through HTTP here. This surface exists so the gateway
can be exercised the same way a real bank's API would be — by curl/Postman
today, by a real integration client later.
"""

import hashlib
import hmac
import json
import logging
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .banking_models import (
    IdempotencyRecord, SimulatedBankTransaction, SimulatedOutcome, VirtualBankAccount,
)
from .payment_gateways import SimulatedBankGateway
from .payment_models import Payment, PaymentMethod, PaymentStatus

logger = logging.getLogger(__name__)


def _require_api_key(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = f'Bearer {settings.BANK_SIMULATOR_API_KEY}'
        provided = request.META.get('HTTP_AUTHORIZATION', '')
        if not hmac.compare_digest(provided, expected):
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def _transaction_body(txn):
    return {
        'reference': txn.reference,
        'status': txn.status,
        'amount_cents': txn.amount_cents,
        'created_at': txn.created_at.isoformat(),
        'settle_after': txn.settle_after.isoformat() if txn.settle_after else None,
        'settled_at': txn.settled_at.isoformat() if txn.settled_at else None,
        'error_message': txn.error_message,
    }


@csrf_exempt
@_require_api_key
@require_http_methods(['POST'])
def create_payment(request):
    """POST /api/bank-simulator/v1/payments/ — supports an Idempotency-Key
    header: a repeated POST with the same key and the same body replays the
    original response instead of creating a second transaction; the same
    key with a different body is a 422."""
    idempotency_key = request.META.get('HTTP_IDEMPOTENCY_KEY', '')
    fingerprint = hashlib.sha256(request.body).hexdigest()

    if idempotency_key:
        existing = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                return JsonResponse(
                    {'error': 'Idempotency-Key was already used with a different request body'}, status=422,
                )
            return JsonResponse(existing.response_body, status=existing.response_status)

    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    account_number = data.get('account_number')
    amount_cents = data.get('amount_cents')
    order_reference = data.get('order_reference', '')
    currency = data.get('currency', settings.STRIPE_CURRENCY)

    if not account_number or not isinstance(amount_cents, int) or amount_cents <= 0:
        return JsonResponse(
            {'error': 'account_number and a positive integer amount_cents are required'}, status=400,
        )

    payment = Payment.objects.create(
        gateway=PaymentMethod.SIMULATED_BANK,
        amount_cents=amount_cents,
        currency=currency,
        status=PaymentStatus.PENDING,
        payment_method_type='bank_transfer',
    )
    SimulatedBankGateway().initiate(
        payment, account_number=account_number, amount_cents=amount_cents, order_reference=order_reference,
    )
    txn = SimulatedBankTransaction.objects.get(payment=payment)

    body = _transaction_body(txn)
    status_code = 202 if txn.status == SimulatedOutcome.PENDING else 402

    if idempotency_key:
        IdempotencyRecord.objects.create(
            key=idempotency_key, endpoint='create_payment', request_fingerprint=fingerprint,
            response_status=status_code, response_body=body,
        )

    return JsonResponse(body, status=status_code)


@_require_api_key
@require_http_methods(['GET'])
def get_payment(request, reference):
    """GET /api/bank-simulator/v1/payments/{reference}/"""
    try:
        txn = SimulatedBankTransaction.objects.get(reference=reference)
    except SimulatedBankTransaction.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse(_transaction_body(txn))


@csrf_exempt
@_require_api_key
@require_http_methods(['POST'])
def cancel_payment(request, reference):
    """POST /api/bank-simulator/v1/payments/{reference}/cancel/"""
    try:
        txn = SimulatedBankTransaction.objects.get(reference=reference)
    except SimulatedBankTransaction.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    SimulatedBankGateway().cancel(txn.payment)
    txn.refresh_from_db()
    return JsonResponse(_transaction_body(txn))


@csrf_exempt
@_require_api_key
@require_http_methods(['POST'])
def refund_payment(request, reference):
    """POST /api/bank-simulator/v1/payments/{reference}/refund/ — optional
    JSON body {"amount_cents": ...} (ignored beyond presence today; see
    payment_views._process_bank_refund for why only full refunds apply)."""
    from .payment_views import _process_bank_refund  # local import: avoid a module-load cycle

    try:
        txn = SimulatedBankTransaction.objects.get(reference=reference)
    except SimulatedBankTransaction.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        data = {}

    try:
        _process_bank_refund(txn.payment, amount_cents=data.get('amount_cents'))
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=409)

    txn.refresh_from_db()
    return JsonResponse(_transaction_body(txn))


@_require_api_key
@require_http_methods(['GET'])
def get_account(request, account_number):
    """GET /api/bank-simulator/v1/accounts/{account_number}/ — unmasked
    since this is a test fixture, not a real bank record."""
    try:
        account = VirtualBankAccount.objects.get(account_number=account_number)
    except VirtualBankAccount.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({
        'account_number': account.account_number,
        'account_holder_name': account.account_holder_name,
        'bank_name': account.bank_name,
        'status': account.status,
        'balance_cents': account.balance_cents,
    })
