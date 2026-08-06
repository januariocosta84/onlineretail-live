"""
TimorPay integration — a trial rail exercising TimorPay (the independent
payment platform at ../timorpay) as an alternative to this app's own
Stripe/bank-transfer/simulated-bank gateways (payment_gateways.py,
payment_views.py). See olretail.payment_models.PaymentMethod.TIMORPAY.

Deliberately isolated in its own module rather than woven into the
existing gateway files — every existing payment path (Stripe, real bank
transfer, cash on delivery, the simulated bank) is untouched. The only
edits elsewhere are additive: one new dispatch branch in
payment_views._process_checkout, one new radio option that already renders
itself from PaymentMethod.choices, and two new URLs.

Money model: platform-held, same shape as PaymentMethod.BANK_TRANSFER — the
buyer's payment lands in one dedicated "TimorMart platform" wallet inside
TimorPay (TIMORPAY_PLATFORM_SELLER_REF below), never an individual
marketplace seller's own TimorPay wallet. TimorMart's existing
SellerBalance/Payout system is what pays sellers out, exactly as it does
today for every other payment method — TimorPay here is only replacing
"buyer wires to our real bank account" with "buyer pays via TimorPay's
manual bank transfer rail." No escrow, no seller-side TimorPay account.
"""
import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .payment_models import Cart, Order, OrderStatus, PaymentMethod

logger = logging.getLogger(__name__)

TIMORPAY_PLATFORM_SELLER_REF = 'timormart-platform-account'


class TimorPayClientError(Exception):
    def __init__(self, message, status_code=None, error_code=None, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details


class TimorPayConnectionError(TimorPayClientError):
    """Raised once retries are exhausted on a network-level failure."""


class TimorPayClient:
    """Thin REST client for TimorPay — see ../timorpay/docs/api.md and
    ../timorpay/examples/timormart_integration/timorpay_client.py (the
    reference version this is adapted from, trimmed to what this trial
    integration actually calls)."""

    def __init__(self, base_url, api_key, timeout=10.0, max_retries=2):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _headers(self, idempotency_key=None):
        headers = {'Authorization': f'Api-Key {self.api_key}', 'Content-Type': 'application/json'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        return headers

    def _request(self, method, path, *, json_body=None, idempotency_key=None, retryable=True):
        url = f'{self.base_url}{path}'
        headers = self._headers(idempotency_key)
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.session.request(method, url, json=json_body, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if retryable and attempt <= self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise TimorPayConnectionError(f'Could not reach TimorPay after {attempt} attempt(s): {exc}') from exc

            if response.status_code >= 500 and retryable and attempt <= self.max_retries:
                time.sleep(min(2 ** attempt, 4))
                continue
            if response.status_code >= 400:
                self._raise_for_error(response)
            return response.json()

    @staticmethod
    def _raise_for_error(response):
        try:
            error = response.json().get('error', {})
        except ValueError:
            error = {}
        raise TimorPayClientError(
            error.get('message', f'TimorPay returned HTTP {response.status_code}'),
            status_code=response.status_code, error_code=error.get('code'), details=error.get('details'),
        )

    def create_payment(self, *, method, buyer_external_ref, order_reference, amount, currency='USD',
                        seller_external_ref='', metadata=None, idempotency_key=None):
        return self._request('POST', '/api/v1/payments/create/', json_body={
            'method': method, 'buyer_external_ref': buyer_external_ref, 'seller_external_ref': seller_external_ref,
            'order_reference': order_reference, 'amount': str(amount), 'currency': currency,
            'metadata': metadata or {},
        }, idempotency_key=idempotency_key or f'order:{order_reference}')

    def get_payment(self, payment_id):
        return self._request('GET', f'/api/v1/payments/{payment_id}/')

    def verify_payment(self, payment_id, note='', idempotency_key=None):
        return self._request(
            'POST', f'/api/v1/payments/{payment_id}/verify/', json_body={'note': note},
            idempotency_key=idempotency_key or f'verify:{payment_id}',
        )


def get_client():
    return TimorPayClient(base_url=settings.TIMORPAY_BASE_URL, api_key=settings.TIMORPAY_API_KEY)


def process_timorpay_checkout(request, form, cart_items):
    """Called from payment_views._process_checkout. Same order-creation
    shape as _process_bank_transfer_checkout there (commission split,
    per-seller delivery fee, platform-held funds) — only the collection
    rail differs: a real call out to TimorPay instead of a static 'here are
    our bank details' page."""
    from .payment_views import _last_item_index_per_seller, _notify  # local import: avoid a module-load cycle

    try:
        with transaction.atomic():
            cart_items = list(cart_items)
            delivery_city = form.cleaned_data['delivery_city']
            last_item_index = _last_item_index_per_seller(cart_items)

            subtotal = sum(item.line_total for item in cart_items)
            subtotal_cents = int(subtotal * 100)
            commission_percent = Decimal(str(settings.COMMISSION_RATE))
            commission_cents = int(subtotal_cents * float(commission_percent))

            orders = []
            allocated_commission_cents = 0
            for index, item in enumerate(cart_items):
                item_cents = int(item.line_total * 100)
                is_last = index == len(cart_items) - 1
                if is_last or subtotal_cents == 0:
                    item_commission_cents = commission_cents - allocated_commission_cents
                else:
                    item_commission_cents = (commission_cents * item_cents) // subtotal_cents
                    allocated_commission_cents += item_commission_cents

                item_commission = Decimal(item_commission_cents) / 100
                delivery_fee = Decimal('0')
                if last_item_index.get(item.product.seller_id) == index:
                    delivery_fee = Decimal(str(settings.DELIVERY_FEE))

                order = Order.objects.create(
                    buyer=request.user,
                    seller=item.product.seller,
                    product=item.product,
                    quantity=item.quantity,
                    price_per_unit=item.product.price,
                    subtotal=item.line_total,
                    commission_amount=item_commission,
                    payment_fee=Decimal('0'),
                    delivery_fee=delivery_fee,
                    total=item.line_total + item_commission + delivery_fee,
                    status=OrderStatus.PENDING_PAYMENT,
                    payment_method=PaymentMethod.TIMORPAY,
                    delivery_address=form.cleaned_data['delivery_address'],
                    delivery_city=delivery_city,
                    delivery_latitude=form.cleaned_data.get('delivery_latitude'),
                    delivery_longitude=form.cleaned_data.get('delivery_longitude'),
                    delivery_phone=form.cleaned_data['delivery_phone'],
                    buyer_notes=form.cleaned_data.get('buyer_notes', ''),
                )
                orders.append(order)

            batch_total = sum(o.total for o in orders)
            # One TimorPay payment covers this whole checkout batch, same as
            # one manual bank transfer already covers a multi-seller cart —
            # order_number is unique per Order and stable, so it doubles as
            # a stable idempotency/order_reference key for the batch.
            order_reference = orders[0].order_number

            payment = get_client().create_payment(
                method='manual_bank_transfer',
                buyer_external_ref=str(request.user.id),
                seller_external_ref=TIMORPAY_PLATFORM_SELLER_REF,
                order_reference=order_reference,
                amount=batch_total,
                currency='USD',
                metadata={
                    'timormart_order_numbers': [o.order_number for o in orders],
                    'buyer_username': request.user.username,
                },
            )

            for order in orders:
                order.payment_reference = payment['id']
                order.save(update_fields=['payment_reference'])
                _notify(
                    order.seller.user,
                    _('New order %(order)s from %(buyer)s for "%(product)s" — awaiting the buyer’s TimorPay payment.')
                    % {'order': order.order_number, 'buyer': request.user.get_full_name() or request.user.username,
                       'product': order.product.name},
                    order=order,
                )

            Cart.objects.filter(buyer=request.user, product__in=[item.product for item in cart_items]).delete()
    except TimorPayClientError as exc:
        # Whole block above rolls back — no orders left half-created.
        logger.error(f"TimorPay checkout failed: {exc}", exc_info=True)
        messages.error(
            request,
            _('TimorPay is temporarily unavailable (%(reason)s) — please choose a different payment method.')
            % {'reason': str(exc)},
        )
        return redirect('olretail:checkout')

    context = {
        'orders': orders,
        'payment': payment,
        'instructions': payment.get('instructions') or {},
        'debug': settings.DEBUG,
    }
    return render(request, 'olretail/timorpay_instructions.html', context)


@login_required
@require_POST
def timorpay_simulate_verification(request, order_id):
    """Dev-only convenience: calls TimorPay's own /verify/ endpoint
    directly, standing in for what a TimorPay ops admin would normally do
    (confirm the bank transfer landed) after checking a real bank
    statement — lets this integration be exercised end-to-end from one
    browser tab instead of needing TimorPay's own admin open in a second
    one. Never available outside DEBUG."""
    if not settings.DEBUG:
        raise Http404

    order = get_object_or_404(Order, id=order_id, buyer=request.user, payment_method=PaymentMethod.TIMORPAY)
    if not order.payment_reference:
        messages.error(request, _('No TimorPay payment on this order.'))
        return redirect('olretail:order_detail', order_id=order.id)

    try:
        get_client().verify_payment(order.payment_reference, note='Simulated from TimorMart checkout (dev only)')
    except TimorPayClientError as exc:
        messages.error(request, _('TimorPay verify failed: %(reason)s') % {'reason': str(exc)})
        return redirect('olretail:order_detail', order_id=order.id)

    messages.success(
        request,
        _('TimorPay payment verified — the webhook should mark the order paid within moments.'),
    )
    return redirect('olretail:order_detail', order_id=order.id)


@csrf_exempt
@require_POST
def timorpay_webhook(request):
    """Receives payment.* events from TimorPay. Verifies the HMAC
    signature (see ../timorpay/apps/webhooks/tasks.py for the sending
    side and ../timorpay/examples/timormart_integration/webhook_receiver.py
    for the reference verifier this mirrors) and rejects stale timestamps
    to prevent replay of a captured call."""
    signature = request.headers.get('X-TimorPay-Signature', '')
    timestamp = request.headers.get('X-TimorPay-Timestamp', '')
    if not signature or not timestamp:
        return HttpResponseBadRequest('Missing signature headers')

    try:
        if abs(time.time() - int(timestamp)) > 5 * 60:
            return HttpResponseBadRequest('Stale timestamp')
    except (ValueError, TypeError):
        return HttpResponseBadRequest('Malformed timestamp')

    raw_body = request.body
    signed_payload = f'{timestamp}.{raw_body.decode()}'.encode()
    expected = hmac.new(settings.TIMORPAY_WEBHOOK_SECRET.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning('TimorPay webhook signature mismatch')
        return HttpResponseBadRequest('Invalid signature')

    try:
        payload = json.loads(raw_body)
    except ValueError:
        return HttpResponseBadRequest('Malformed JSON')

    event = payload.get('event')
    data = payload.get('data', {})
    logger.info(f"TimorPay webhook received: {event} ({data.get('id')})")

    if event == 'payment.completed':
        _apply_payment_completed(data)
    elif event in ('payment.failed', 'payment.cancelled'):
        _apply_payment_failed(data)
    # payment.created / payment.pending: nothing to do — the instructions
    # were already shown synchronously when the payment was created.

    return HttpResponse(status=200)


def _apply_payment_completed(data):
    from .payment_views import _mark_bank_transfer_paid  # reused as-is — gateway-agnostic despite the name, see its own docstring

    payment_id = data.get('id')
    orders = Order.objects.filter(payment_method=PaymentMethod.TIMORPAY, payment_reference=payment_id)
    for order in orders:
        if order.status == OrderStatus.PENDING_PAYMENT:
            _mark_bank_transfer_paid(order)
            logger.info(f"TimorPay payment {payment_id} confirmed for order {order.order_number}")


def _apply_payment_failed(data):
    payment_id = data.get('id')
    orders = Order.objects.filter(
        payment_method=PaymentMethod.TIMORPAY, payment_reference=payment_id, status=OrderStatus.PENDING_PAYMENT,
    )
    for order in orders:
        order.status = OrderStatus.CANCELLED
        order.save(update_fields=['status'])
        logger.info(f"TimorPay payment {payment_id} failed/cancelled for order {order.order_number}")
