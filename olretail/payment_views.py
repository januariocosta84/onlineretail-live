import stripe
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.contrib import messages
from django.db import transaction

from olretail.models import (
    Product, Seller, SellerType, SellerVerificationStatus, Buyer, Courier, CourierVerificationStatus,
)
from olretail.decorators import seller_required, courier_required
from .payment_models import (
    Cart, Order, Payment, OrderStatus, PaymentMethod, PaymentStatus, Transaction,
    TransactionType, SellerBalance, Dispute, DisputeStatus, DisputeResolution, DeliveryUpdate,
    PlatformSettings, Notification, Rating, CourierRating,
)
from .payment_forms import (
    CheckoutForm, DisputeForm, SellerDisputeResponseForm, SellerPaymentInstructionsForm,
    ShipOrderForm, DeliveryUpdateForm, DeliveryProofForm, SubscriptionRequestForm,
    CourierVerificationForm, SellerCompanyInfoForm, SellerVerificationForm,
)
from .subscription_models import (
    FREE_PRODUCT_LIMIT, PLAN_PRICES, SellerSubscription, SubscriptionRequest, SubscriptionRequestStatus,
)

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


def _notify(user, message, order=None):
    """Create an in-app notification for `user` (bell icon in the header —
    see context_processors.notifications and the /notifications/ page),
    and email the same message so it reaches someone who isn't actively
    checking the site (console-only in dev unless EMAIL_HOST is set — see
    settings.py). Email failures never break the calling flow."""
    Notification.objects.create(recipient=user, order=order, message=message)
    if user.email:
        subject = (
            _('TimorMart — order %(order)s') % {'order': order.order_number}
            if order else _('TimorMart notification')
        )
        try:
            send_mail(subject, message, None, [user.email], fail_silently=True)
        except Exception:
            logger.warning(f"Failed to email notification to {user.email}", exc_info=True)


def _parse_int(raw, default=1):
    """Parse an integer POST value (cart quantity, rating score), tolerating
    non-numeric input (e.g. a hand-crafted or garbled request) instead of
    raising."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────────
# CART VIEWS
# ──────────────────────────────────────────────────────────────────

@login_required
def cart(request):
    """Display shopping cart."""
    cart_items = Cart.objects.filter(buyer=request.user).select_related('product')
    cart_total = sum(item.line_total for item in cart_items)
    
    context = {
        'cart_items': cart_items,
        'cart_total': cart_total,
    }
    return render(request, 'olretail/cart.html', context)


@login_required
@require_POST
def add_to_cart(request, product_id):
    """Add product to cart."""
    product = get_object_or_404(Product, id=product_id, status='approved')

    if not product.cart_purchasable:
        messages.error(request, _('This item can only be purchased by contacting the seller directly.'))
        return redirect(product.get_absolute_url())

    if product.quantity <= 0:
        messages.error(request, _('This product is out of stock.'))
        return redirect(product.get_absolute_url())
    
    quantity = _parse_int(request.POST.get('quantity'), default=1)
    if quantity < 1:
        quantity = 1
    if quantity > product.quantity:
        quantity = product.quantity

    cart_item, created = Cart.objects.get_or_create(
        buyer=request.user,
        product=product,
        defaults={'quantity': quantity}
    )
    
    if not created:
        cart_item.quantity += quantity
        if cart_item.quantity > product.quantity:
            cart_item.quantity = product.quantity
        cart_item.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'added',
            'cart_count': Cart.objects.filter(buyer=request.user).count()
        })
    
    messages.success(request, _('Product added to cart.'))
    return redirect('olretail:cart')


@login_required
@require_POST
def update_cart(request, cart_id):
    """Update cart item quantity."""
    cart_item = get_object_or_404(Cart, id=cart_id, buyer=request.user)
    quantity = _parse_int(request.POST.get('quantity'), default=1)

    if quantity > 0 and quantity <= cart_item.product.quantity:
        cart_item.quantity = quantity
        cart_item.save()
        messages.success(request, _('Cart updated.'))
    elif quantity > cart_item.product.quantity:
        messages.error(request, _('Not enough stock available.'))
    else:
        cart_item.delete()
        messages.success(request, _('Item removed from cart.'))
    
    return redirect('olretail:cart')


@login_required
@require_POST
def remove_from_cart(request, cart_id):
    """Remove item from cart."""
    cart_item = get_object_or_404(Cart, id=cart_id, buyer=request.user)
    cart_item.delete()
    messages.success(request, _('Item removed from cart.'))
    return redirect('olretail:cart')


@login_required
@require_POST
def clear_cart(request):
    """Clear entire cart."""
    Cart.objects.filter(buyer=request.user).delete()
    messages.success(request, _('Cart cleared.'))
    return redirect('olretail:cart')

# ──────────────────────────────────────────────────────────────────
# CHECKOUT VIEWS
# ──────────────────────────────────────────────────────────────────

@login_required
def checkout(request):
    """Checkout form: collect delivery info."""
    cart_items = Cart.objects.filter(buyer=request.user).select_related('product')
    
    if not cart_items.exists():
        messages.warning(request, _('Your cart is empty.'))
        return redirect('olretail:cart')
    
    # Check if all products are still available
    for item in cart_items:
        if not item.product.cart_purchasable:
            messages.error(
                request,
                _('%(product)s can only be purchased by contacting the seller directly — remove it from your cart.')
                % {'product': item.product.name}
            )
            return redirect('olretail:cart')
        if item.quantity > item.product.quantity:
            messages.error(
                request,
                _('%(product)s has only %(qty)d available.') % {
                    'product': item.product.name,
                    'qty': item.product.quantity
                }
            )
            return redirect('olretail:cart')
    
    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            return _process_checkout(request, form, cart_items)
    else:
        # Pre-fill form with buyer's info
        try:
            buyer_profile = request.user.buyer
            initial_data = {
                'delivery_address': buyer_profile.address,
                'delivery_phone': buyer_profile.mobile,
            }
        except Buyer.DoesNotExist:
            initial_data = {}
        
        form = CheckoutForm(initial=initial_data)
    
    cart_total = sum(item.line_total for item in cart_items)
    commission_rate = Decimal(str(settings.COMMISSION_RATE))
    platform_fee = cart_total * commission_rate
    payment_fee = Decimal(str(settings.STRIPE_FEE_FIXED))
    estimated_total = cart_total + platform_fee + payment_fee

    sellers_missing_instructions = {
        item.product.seller.get_name for item in cart_items
        if not item.product.seller.payment_instructions.strip()
    }

    context = {
        'form': form,
        'cart_items': cart_items,
        'cart_total': cart_total,
        'platform_fee': platform_fee,
        'payment_fee': payment_fee,
        'estimated_total': estimated_total,
        'sellers_missing_instructions': sellers_missing_instructions,
    }
    return render(request, 'olretail/checkout.html', context)


def _process_checkout(request, form, cart_items):
    """Create orders, then either start a Stripe payment or hand the buyer
    direct bank-transfer instructions, depending on the chosen method."""
    payment_method = form.cleaned_data['payment_method']

    if payment_method == PaymentMethod.BANK_TRANSFER:
        missing = {
            item.product.seller.get_name for item in cart_items
            if not item.product.seller.payment_instructions.strip()
        }
        if missing:
            messages.error(
                request,
                _('%(sellers)s haven\'t set up payment details yet — choose Card, or contact them.')
                % {'sellers': ', '.join(missing)},
            )
            return redirect('olretail:checkout')
        return _process_bank_transfer_checkout(request, form, cart_items)

    return _process_stripe_checkout(request, form, cart_items)


def _process_bank_transfer_checkout(request, form, cart_items):
    """Create one order per cart item, no platform commission — the buyer
    pays the seller directly and the platform never touches the money."""
    with transaction.atomic():
        orders = []
        for item in cart_items:
            order = Order.objects.create(
                buyer=request.user,
                seller=item.product.seller,
                product=item.product,
                quantity=item.quantity,
                price_per_unit=item.product.price,
                subtotal=item.line_total,
                commission_amount=Decimal('0'),
                payment_fee=Decimal('0'),
                total=item.line_total,
                status=OrderStatus.PENDING_PAYMENT,
                payment_method=PaymentMethod.BANK_TRANSFER,
                delivery_address=form.cleaned_data['delivery_address'],
                delivery_city=form.cleaned_data['delivery_city'],
                delivery_phone=form.cleaned_data['delivery_phone'],
                buyer_notes=form.cleaned_data.get('buyer_notes', ''),
            )
            orders.append(order)
            _notify(
                order.seller.user,
                _('New order %(order)s from %(buyer)s for “%(product)s” — awaiting their bank/mobile transfer.')
                % {'order': order.order_number, 'buyer': request.user.get_full_name() or request.user.username,
                   'product': order.product.name},
                order=order,
            )

    return render(request, 'olretail/bank_transfer_instructions.html', {'orders': orders})


def _process_stripe_checkout(request, form, cart_items):
    """A cart can span several sellers at once. Stripe only lets us charge
    one combined PaymentIntent, so we create one Order per line item (each
    keeps its own seller/commission) and point them all at the single
    shared Payment — see Order.payment. The commission/processing fee is
    split across orders proportionally to their share of the subtotal so
    each order's total is accurate and they sum back to what Stripe
    actually charges (remainder cents land on the last item)."""
    with transaction.atomic():
        cart_items = list(cart_items)
        subtotal = sum(item.line_total for item in cart_items)
        subtotal_cents = int(subtotal * 100)

        commission_percent = Decimal(str(settings.COMMISSION_RATE))
        commission_cents = int(subtotal_cents * float(commission_percent))

        # Stripe fee
        total_cents = subtotal_cents + commission_cents
        stripe_fee_percent = Decimal(str(settings.STRIPE_FEE_PERCENT))
        stripe_fee_fixed_cents = int(settings.STRIPE_FEE_FIXED * 100)
        payment_fee_cents = int(total_cents * float(stripe_fee_percent)) + stripe_fee_fixed_cents

        final_total_cents = total_cents + payment_fee_cents

        # Create orders (one per seller per product), splitting the shared
        # commission/fee proportionally by each item's share of the subtotal.
        orders = []
        allocated_commission_cents = 0
        allocated_fee_cents = 0
        for index, item in enumerate(cart_items):
            item_cents = int(item.line_total * 100)
            is_last = index == len(cart_items) - 1
            if is_last or subtotal_cents == 0:
                item_commission_cents = commission_cents - allocated_commission_cents
                item_fee_cents = payment_fee_cents - allocated_fee_cents
            else:
                item_commission_cents = (commission_cents * item_cents) // subtotal_cents
                item_fee_cents = (payment_fee_cents * item_cents) // subtotal_cents
                allocated_commission_cents += item_commission_cents
                allocated_fee_cents += item_fee_cents

            item_commission = Decimal(item_commission_cents) / 100
            item_fee = Decimal(item_fee_cents) / 100

            order = Order.objects.create(
                buyer=request.user,
                seller=item.product.seller,
                product=item.product,
                quantity=item.quantity,
                price_per_unit=item.product.price,
                subtotal=item.line_total,
                commission_amount=item_commission,
                payment_fee=item_fee,
                total=item.line_total + item_commission + item_fee,
                status=OrderStatus.PENDING_PAYMENT,
                payment_method=PaymentMethod.STRIPE,
                delivery_address=form.cleaned_data['delivery_address'],
                delivery_city=form.cleaned_data['delivery_city'],
                delivery_phone=form.cleaned_data['delivery_phone'],
                buyer_notes=form.cleaned_data.get('buyer_notes', ''),
            )
            orders.append(order)

        # The buyer is redirected to this order's confirmation page after
        # payment, which then shows every sibling order (see payment_confirmation).
        first_order = orders[0]

        try:
            payment_intent = stripe.PaymentIntent.create(
                amount=final_total_cents,
                currency=settings.STRIPE_CURRENCY,
                metadata={
                    'order_id': first_order.order_number,
                    'buyer_id': request.user.id,
                    'order_count': len(orders),
                },
            )

            payment = Payment.objects.create(
                stripe_payment_intent_id=payment_intent['id'],
                amount_cents=final_total_cents,
                status=PaymentStatus.PENDING,
                payment_method_type='card',
            )
            Order.objects.filter(id__in=[o.id for o in orders]).update(payment=payment)

            # Store order IDs for webhook
            request.session['order_ids'] = [o.id for o in orders]

            context = {
                'order': first_order,
                'payment': payment,
                'client_secret': payment_intent['client_secret'],
                'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
                'orders': orders,
                'final_total': final_total_cents / 100,
            }
            return render(request, 'olretail/payment.html', context)

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error during checkout: {str(e)}")
            messages.error(request, _('Payment processing error. Please try again.'))
            return redirect('olretail:checkout')


def _mark_payment_succeeded(payment, charge_id, source):
    """Apply payment-succeeded side effects to every order that shares this
    Payment (a single Stripe charge can cover a cart spanning several
    sellers): mark each order paid, record its commission, credit its
    seller's balance, decrement its stock, and clear its cart entry. Shared
    by the webhook and the confirmation-page reconciliation fallback
    (Stripe may confirm the card before the webhook arrives, or the webhook
    may never arrive in local dev)."""
    with transaction.atomic():
        payment.stripe_charge_id = charge_id
        payment.status = PaymentStatus.SUCCEEDED
        payment.succeeded_at = timezone.now()
        payment.webhook_received = True
        payment.webhook_received_at = timezone.now()
        payment.save()

        now = timezone.now()
        order_numbers = []
        for order in payment.orders.select_related('product', 'seller').all():
            order.status = OrderStatus.PAID
            order.paid_at = now
            order.save()

            Transaction.objects.create(
                order=order,
                seller=order.seller,
                amount_cents=int(order.commission_amount * 100),
                transaction_type=TransactionType.COMMISSION,
                description=f"Commission on order {order.order_number}",
            )

            seller_balance, _created = SellerBalance.objects.get_or_create(seller=order.seller)
            seller_balance.add_commission(int(order.commission_amount * 100))

            product = Product.objects.select_for_update().get(pk=order.product_id)
            product.quantity = max(product.quantity - order.quantity, 0)
            product.save(update_fields=['quantity'])

            Cart.objects.filter(buyer=order.buyer, product=order.product).delete()
            order_numbers.append(order.order_number)

            _notify(
                order.seller.user,
                _('Payment received for order %(order)s from %(buyer)s — “%(product)s”.')
                % {'order': order.order_number, 'buyer': order.buyer.get_full_name() or order.buyer.username,
                   'product': order.product.name},
                order=order,
            )
            _notify(
                order.buyer,
                _('Your payment for order %(order)s was successful.') % {'order': order.order_number},
                order=order,
            )

    logger.info(f"Payment succeeded for order(s) {', '.join(order_numbers)} (via {source})")


def _reconcile_payment(order):
    """Fallback for when Stripe's webhook hasn't reached us yet (or won't,
    e.g. localhost in dev): ask Stripe directly whether the PaymentIntent
    succeeded and, if so, apply the same effects the webhook would have."""
    payment = order.payment
    if payment is None:
        return

    if payment.status == PaymentStatus.SUCCEEDED:
        return

    try:
        intent = stripe.PaymentIntent.retrieve(payment.stripe_payment_intent_id)
    except stripe.error.StripeError as e:
        logger.warning(f"Payment reconciliation failed for order {order.order_number}: {e}")
        return

    if intent.status == 'succeeded':
        charges = intent.get('charges', {}).get('data', [])
        charge_id = charges[0]['id'] if charges else ''
        _mark_payment_succeeded(payment, charge_id, source='reconciliation')


@login_required
def payment_confirmation(request, order_id):
    """Confirmation page after successful payment."""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if order.status == OrderStatus.PENDING_PAYMENT:
        _reconcile_payment(order)
        order.refresh_from_db()

    # A single checkout/charge can cover several orders (one per seller) —
    # show every sibling order sharing this order's Payment, if any.
    if order.payment_id:
        related_orders = order.payment.orders.filter(buyer=request.user).order_by('-created_at')
    else:
        related_orders = Order.objects.filter(pk=order.pk)

    context = {
        'order': order,
        'related_orders': related_orders,
    }
    return render(request, 'olretail/payment_confirmation.html', context)


# ──────────────────────────────────────────────────────────────────
# BANK / MOBILE TRANSFER (direct buyer → seller, no platform commission)
# ──────────────────────────────────────────────────────────────────

def _mark_bank_transfer_paid(order):
    """Seller confirmed they received the buyer's direct transfer. No
    commission is taken — the platform never touched this money."""
    with transaction.atomic():
        order.status = OrderStatus.PAID
        order.paid_at = timezone.now()
        order.save()

        product = Product.objects.select_for_update().get(pk=order.product_id)
        product.quantity = max(product.quantity - order.quantity, 0)
        product.save(update_fields=['quantity'])

        Cart.objects.filter(buyer=order.buyer, product=order.product).delete()

    logger.info(f"Bank-transfer payment confirmed for order {order.order_number}")


@login_required
@require_POST
def mark_payment_sent(request, order_id):
    """Buyer confirms they've sent the bank/mobile transfer."""
    order = get_object_or_404(
        Order, id=order_id, buyer=request.user, payment_method=PaymentMethod.BANK_TRANSFER
    )
    if order.status != OrderStatus.PENDING_PAYMENT:
        messages.error(request, _('This order is not awaiting a transfer.'))
        return redirect('olretail:order_detail', order_id=order.id)

    order.status = OrderStatus.PAYMENT_REPORTED
    order.payment_reported_at = timezone.now()
    order.save(update_fields=['status', 'payment_reported_at'])
    _notify(
        order.seller.user,
        _('%(buyer)s says they\'ve sent payment for order %(order)s — please confirm receipt.')
        % {'buyer': order.buyer.get_full_name() or order.buyer.username, 'order': order.order_number},
        order=order,
    )
    messages.success(request, _('Thanks — the seller has been notified to confirm receipt.'))
    return redirect('olretail:order_detail', order_id=order.id)


@login_required
@require_POST
def confirm_payment_received(request, order_id):
    """Seller confirms they received the buyer's direct transfer."""
    order = get_object_or_404(Order, id=order_id, payment_method=PaymentMethod.BANK_TRANSFER)
    try:
        if order.seller != request.user.seller:
            messages.error(request, _('Permission denied.'))
            return redirect('olretail:index')
    except Seller.DoesNotExist:
        messages.error(request, _('You must be a seller to confirm payments.'))
        return redirect('olretail:index')

    if order.status not in (OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REPORTED):
        messages.error(request, _('This order is not awaiting payment confirmation.'))
        return redirect('olretail:order_detail', order_id=order.id)

    _mark_bank_transfer_paid(order)
    _notify(
        order.buyer,
        _('%(seller)s confirmed your payment for order %(order)s.')
        % {'seller': order.seller.get_name, 'order': order.order_number},
        order=order,
    )
    messages.success(request, _('Payment confirmed — the order is now marked as paid.'))
    return redirect('olretail:order_detail', order_id=order.id)


@seller_required
def seller_payment_settings(request):
    """Seller's bank/mobile money details shown to buyers who pay by direct
    transfer, plus (for company sellers) editable company info and business
    verification — all three live on this one settings page."""
    seller = request.user.seller
    if request.method == 'POST':
        form = SellerPaymentInstructionsForm(request.POST, instance=seller)
        if form.is_valid():
            form.save()
            messages.success(request, _('Payment details saved.'))
            return redirect('olretail:seller_payment_settings')
    else:
        # Nudge a first-time value from the company bank account collected
        # at registration — never overwrites anything a seller already typed
        # here themselves.
        initial = {}
        if not seller.payment_instructions and seller.company_bank_account:
            initial['payment_instructions'] = seller.company_bank_account
        form = SellerPaymentInstructionsForm(instance=seller, initial=initial)

    context = {'form': form, 'seller': seller}
    if seller.seller_type == SellerType.COMPANY:
        context['company_form'] = SellerCompanyInfoForm(instance=seller)
        context['verification_form'] = SellerVerificationForm()
    return render(request, 'olretail/seller_payment_settings.html', context)


@seller_required
@require_POST
def seller_company_info(request):
    """Company seller edits their business details after registration.
    Changing the identity fields (name/TIN/address) voids an existing
    verification — the approved document no longer matches what's on file."""
    seller = request.user.seller
    if seller.seller_type != SellerType.COMPANY:
        messages.error(request, _('Company info only applies to company seller accounts.'))
        return redirect('olretail:seller_payment_settings')

    identity_fields = ('company_name', 'company_tin', 'company_address')
    before = {name: getattr(seller, name) for name in identity_fields}

    form = SellerCompanyInfoForm(request.POST, instance=seller)
    if form.is_valid():
        updated = form.save(commit=False)
        identity_changed = any(form.cleaned_data[name] != before[name] for name in identity_fields)
        if identity_changed and updated.verification_status == SellerVerificationStatus.VERIFIED:
            updated.verification_status = SellerVerificationStatus.PENDING
            updated.verification_note = ''
            updated.verified_at = None
            updated.verified_by = None
        updated.save()
        messages.success(request, _('Company information saved.'))
    else:
        messages.error(request, _('Please correct the errors below.'))
    return redirect('olretail:seller_payment_settings')


@seller_required
@require_POST
def seller_submit_verification(request):
    """Company seller submits (or resubmits) a business registration
    document for admin review — a trust badge for buyers, not a
    requirement to keep selling."""
    seller = request.user.seller
    if seller.seller_type != SellerType.COMPANY:
        messages.error(request, _('Business verification only applies to company seller accounts.'))
        return redirect('olretail:seller_payment_settings')

    form = SellerVerificationForm(request.POST, request.FILES)
    if form.is_valid():
        seller.business_document = form.cleaned_data['business_document']
        seller.verification_status = SellerVerificationStatus.PENDING
        seller.verification_note = ''
        seller.save(update_fields=['business_document', 'verification_status', 'verification_note'])
        messages.success(request, _('Document submitted — an administrator will review it shortly.'))
    else:
        messages.error(request, _('Please correct the errors below.'))
    return redirect('olretail:seller_payment_settings')


@seller_required
def seller_subscription(request):
    """Listing plan: free sellers are capped at FREE_PRODUCT_LIMIT products.
    Upgrading is bank-transfer-style — the seller pays the platform
    directly and reports it here; an admin confirms it (see the dashboard)
    before it activates. There's no automated billing."""
    seller = request.user.seller
    subscription, _created = SellerSubscription.objects.get_or_create(seller=seller)
    pending_request = SubscriptionRequest.objects.filter(
        seller=seller, status=SubscriptionRequestStatus.PENDING
    ).first()

    if request.method == 'POST':
        if pending_request:
            messages.error(request, _('You already have a pending subscription request awaiting confirmation.'))
            return redirect('olretail:seller_subscription')
        form = SubscriptionRequestForm(request.POST)
        if form.is_valid():
            plan = form.cleaned_data['plan']
            SubscriptionRequest.objects.create(
                seller=seller,
                plan=plan,
                amount=PLAN_PRICES[plan],
                payment_reference=form.cleaned_data['payment_reference'],
            )
            messages.success(
                request, _("Thanks — your payment report was submitted. An admin will confirm it shortly.")
            )
            return redirect('olretail:seller_subscription')
        messages.error(request, _('Please correct the errors below.'))
    else:
        form = SubscriptionRequestForm()

    return render(
        request,
        'olretail/seller_subscription.html',
        {
            'subscription': subscription,
            'pending_request': pending_request,
            'form': form,
            'plan_prices': PLAN_PRICES,
            'free_limit': FREE_PRODUCT_LIMIT,
            'platform_payment_instructions': (
                PlatformSettings.load().payment_instructions or settings.PLATFORM_PAYMENT_INSTRUCTIONS
            ),
            'recent_requests': SubscriptionRequest.objects.filter(seller=seller)[:5],
        },
    )


# ──────────────────────────────────────────────────────────────────
# ORDER VIEWS (Buyer)
# ──────────────────────────────────────────────────────────────────

@login_required
def buyer_orders(request):
    """View buyer's order history."""
    orders = Order.objects.filter(buyer=request.user).select_related(
        'product', 'seller'
    ).order_by('-created_at')
    
    # Group by status
    status_filter = request.GET.get('status')
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    context = {
        'orders': orders,
        'order_statuses': OrderStatus.choices,
        'current_status': status_filter,
    }
    return render(request, 'olretail/buyer_orders.html', context)


@login_required
@require_POST
def cancel_order(request, order_id):
    """Buyer cancels an order before it's been paid — nothing to restock
    since stock is only decremented once an order reaches Paid."""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if order.status not in (OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REPORTED):
        messages.error(request, _('This order can no longer be cancelled — it has already been paid or is past that stage.'))
        return redirect('olretail:order_detail', order_id=order.id)

    if order.payment_id and order.payment.stripe_payment_intent_id:
        try:
            stripe.PaymentIntent.cancel(order.payment.stripe_payment_intent_id)
        except stripe.error.StripeError as e:
            logger.warning(f"Could not cancel Stripe PaymentIntent for order {order.order_number}: {e}")

    order.status = OrderStatus.CANCELLED
    order.save(update_fields=['status'])
    _notify(
        order.seller.user,
        _('%(buyer)s cancelled order %(order)s before paying.')
        % {'buyer': order.buyer.get_full_name() or order.buyer.username, 'order': order.order_number},
        order=order,
    )
    messages.success(request, _('Order %(order)s was cancelled.') % {'order': order.order_number})
    return redirect('olretail:buyer_orders')


@login_required
def order_detail(request, order_id):
    """View order detail."""
    order = get_object_or_404(Order, id=order_id)
    
    # Check permissions
    is_buyer = order.buyer == request.user
    is_seller = request.user.groups.filter(name='Seller').exists() and order.seller.user == request.user
    is_courier = bool(
        order.assigned_courier_id
        and hasattr(request.user, 'courier')
        and order.assigned_courier_id == request.user.courier.id
    )
    is_admin = request.user.is_staff

    if not (is_buyer or is_seller or is_courier or is_admin):
        messages.error(request, _('You do not have permission to view this order.'))
        return redirect('olretail:index')

    context = {
        'order': order,
        'is_buyer': is_buyer,
        'is_seller': is_seller,
        'is_courier': is_courier,
        'is_admin': is_admin,
        'delivery_updates': order.delivery_updates.all(),
    }
    if is_seller and order.status == OrderStatus.PAID:
        context['ship_form'] = ShipOrderForm(order=order)
    if is_seller and order.status == OrderStatus.SHIPPED:
        context['delivery_update_form'] = DeliveryUpdateForm()
    if (is_seller or is_courier) and order.status == OrderStatus.SHIPPED:
        context['delivery_proof_form'] = DeliveryProofForm()
    if is_admin and order.status == OrderStatus.SHIPPED:
        context['couriers'] = Courier.objects.select_related('user').order_by('user__first_name')
    if is_buyer and order.status == OrderStatus.DELIVERED:
        context['rating'] = getattr(order, 'rating', None)
        context['courier_rating'] = getattr(order, 'courier_rating', None)
    return render(request, 'olretail/order_detail.html', context)


@login_required
@require_POST
def rate_order(request, order_id):
    """Buyer rates the product on a Delivered order — one rating per order
    (a repeat purchase can be rated again, a duplicate submission on the
    same order can't)."""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if order.status != OrderStatus.DELIVERED:
        messages.error(request, _('You can only rate a product after it has been delivered.'))
        return redirect('olretail:order_detail', order_id=order.id)

    if hasattr(order, 'rating'):
        messages.error(request, _('You already rated this order.'))
        return redirect('olretail:order_detail', order_id=order.id)

    score = _parse_int(request.POST.get('score'), default=0)
    if score not in dict(Rating.SCORE_CHOICES):
        messages.error(request, _('Please choose a rating from 1 to 5 stars.'))
        return redirect('olretail:order_detail', order_id=order.id)

    Rating.objects.create(buyer=request.user, product=order.product, order=order, score=score)
    messages.success(request, _('Thanks for your rating!'))
    return redirect('olretail:order_detail', order_id=order.id)


@login_required
@require_POST
def rate_courier(request, order_id):
    """Buyer rates the courier who delivered a Delivered order — one rating
    per order, independent of the product Rating above."""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)

    if order.status != OrderStatus.DELIVERED:
        messages.error(request, _('You can only rate a courier after the order has been delivered.'))
        return redirect('olretail:order_detail', order_id=order.id)

    if not order.assigned_courier_id:
        messages.error(request, _('This order has no assigned courier to rate.'))
        return redirect('olretail:order_detail', order_id=order.id)

    if hasattr(order, 'courier_rating'):
        messages.error(request, _('You already rated this courier.'))
        return redirect('olretail:order_detail', order_id=order.id)

    score = _parse_int(request.POST.get('score'), default=0)
    if score not in dict(CourierRating.SCORE_CHOICES):
        messages.error(request, _('Please choose a rating from 1 to 5 stars.'))
        return redirect('olretail:order_detail', order_id=order.id)

    CourierRating.objects.create(buyer=request.user, courier=order.assigned_courier, order=order, score=score)
    messages.success(request, _('Thanks for rating the courier!'))
    return redirect('olretail:order_detail', order_id=order.id)


# ──────────────────────────────────────────────────────────────────
# SELLER VIEWS (Orders & Balance)
# ──────────────────────────────────────────────────────────────────

@login_required
def seller_orders(request):
    """View seller's orders."""
    try:
        seller = request.user.seller
    except Seller.DoesNotExist:
        messages.error(request, _('You must be a seller to view this page.'))
        return redirect('olretail:index')
    
    orders = Order.objects.filter(seller=seller).select_related(
        'product', 'buyer'
    ).order_by('-created_at')
    
    status_filter = request.GET.get('status')
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    context = {
        'orders': orders,
        'order_statuses': OrderStatus.choices,
        'current_status': status_filter,
    }
    return render(request, 'olretail/seller_orders.html', context)


@login_required
def seller_balance(request):
    """View seller's balance and earnings."""
    try:
        seller = request.user.seller
        balance, _ = SellerBalance.objects.get_or_create(seller=seller)
    except Seller.DoesNotExist:
        messages.error(request, _('You must be a seller to view this page.'))
        return redirect('olretail:index')
    
    # Get transaction history
    transactions = Transaction.objects.filter(seller=seller).order_by('-created_at')[:20]
    
    # Get payout history
    payouts = seller.payouts.order_by('-scheduled_date')[:10]
    
    context = {
        'balance': balance,
        'transactions': transactions,
        'payouts': payouts,
    }
    return render(request, 'olretail/seller_balance.html', context)


@login_required
@require_POST
def seller_update_order_status(request, order_id):
    """Seller marks a paid order as shipped, optionally assigning a courier.
    Delivery (with required photo proof) is handled by mark_delivered."""
    order = get_object_or_404(Order, id=order_id)

    try:
        seller = request.user.seller
        if order.seller != seller:
            messages.error(request, _('Permission denied.'))
            return redirect('olretail:order_detail', order_id=order.id)
    except Seller.DoesNotExist:
        messages.error(request, _('You must be a seller to update orders.'))
        return redirect('olretail:order_detail', order_id=order.id)

    if request.POST.get('status') != OrderStatus.SHIPPED:
        messages.error(request, _('Unknown action.'))
        return redirect('olretail:order_detail', order_id=order.id)

    if order.status != OrderStatus.PAID:
        messages.error(request, _('Only paid orders can be marked as shipped.'))
        return redirect('olretail:order_detail', order_id=order.id)

    form = ShipOrderForm(request.POST, order=order)
    if form.is_valid():
        order.status = OrderStatus.SHIPPED
        order.shipped_at = timezone.now()
        order.courier_name = form.cleaned_data['courier_name']
        order.tracking_number = form.cleaned_data['tracking_number']
        order.assigned_courier = form.cleaned_data['assigned_courier']
        order.save()
        _notify(
            order.buyer,
            _('Your order %(order)s has shipped.') % {'order': order.order_number},
            order=order,
        )
        messages.success(request, _('Order marked as shipped.'))
    else:
        messages.error(request, _('Please correct the errors below.'))

    return redirect('olretail:order_detail', order_id=order.id)


@login_required
@require_POST
def mark_delivered(request, order_id):
    """Seller (self-delivery) or the assigned courier confirms delivery.
    A photo is required — see DeliveryProofForm."""
    order = get_object_or_404(Order, id=order_id)

    is_owning_seller = hasattr(request.user, 'seller') and order.seller_id == request.user.seller.id
    is_assigned_courier = (
        order.assigned_courier_id
        and hasattr(request.user, 'courier')
        and order.assigned_courier_id == request.user.courier.id
    )
    if not (is_owning_seller or is_assigned_courier):
        messages.error(request, _('Permission denied.'))
        return redirect('olretail:index')

    if order.status != OrderStatus.SHIPPED:
        messages.error(request, _('Only shipped orders can be marked as delivered.'))
        return redirect('olretail:order_detail', order_id=order.id)

    form = DeliveryProofForm(request.POST, request.FILES)
    if form.is_valid():
        order.status = OrderStatus.DELIVERED
        order.delivered_at = timezone.now()
        order.delivery_photo = form.cleaned_data['photo']
        order.save()
        _notify(
            order.buyer,
            _('Your order %(order)s has been delivered.') % {'order': order.order_number},
            order=order,
        )
        messages.success(request, _('Order marked as delivered.'))
        if is_assigned_courier:
            return redirect('olretail:courier_deliveries')
    else:
        messages.error(request, _('A delivery photo is required to confirm delivery.'))

    return redirect('olretail:order_detail', order_id=order.id)


@courier_required
def courier_deliveries(request):
    """Courier's dashboard: orders assigned to them, pending and delivered."""
    courier = request.user.courier
    orders = Order.objects.filter(assigned_courier=courier).select_related('product', 'buyer', 'seller')
    context = {
        'pending': orders.filter(status=OrderStatus.SHIPPED).order_by('-shipped_at'),
        'delivered': orders.filter(status=OrderStatus.DELIVERED).order_by('-delivered_at')[:20],
        'courier': courier,
        'verification_form': CourierVerificationForm(),
    }
    return render(request, 'olretail/courier_deliveries.html', context)


@courier_required
@require_POST
def courier_submit_verification(request):
    """Courier submits (or resubmits) their ID document photo for admin
    review — required before they can be assigned any deliveries."""
    courier = request.user.courier
    form = CourierVerificationForm(request.POST, request.FILES)
    if form.is_valid():
        courier.id_document = form.cleaned_data['id_document']
        courier.verification_status = CourierVerificationStatus.PENDING
        courier.verification_note = ''
        courier.save(update_fields=['id_document', 'verification_status', 'verification_note'])
        messages.success(request, _('ID submitted — an administrator will review it shortly.'))
    else:
        messages.error(request, _('Please correct the errors below.'))
    return redirect('olretail:courier_deliveries')


@login_required
@require_POST
def add_delivery_update(request, order_id):
    """Seller posts a free-text status update the buyer can see."""
    order = get_object_or_404(Order, id=order_id)

    try:
        if order.seller != request.user.seller:
            messages.error(request, _('Permission denied.'))
            return redirect('olretail:index')
    except Seller.DoesNotExist:
        messages.error(request, _('You must be a seller to post delivery updates.'))
        return redirect('olretail:index')

    form = DeliveryUpdateForm(request.POST)
    if form.is_valid():
        update = form.save(commit=False)
        update.order = order
        update.save()
        _notify(
            order.buyer,
            _('Delivery update for order %(order)s: %(note)s') % {'order': order.order_number, 'note': update.note},
            order=order,
        )
        messages.success(request, _('Update posted.'))
    else:
        messages.error(request, _('Please enter a status update.'))

    return redirect('olretail:order_detail', order_id=order.id)

# ──────────────────────────────────────────────────────────────────
# WEBHOOK (Stripe)
# ──────────────────────────────────────────────────────────────────

@require_POST
def stripe_webhook(request):
    """Handle Stripe webhook events."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error("Stripe webhook: invalid payload")
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Stripe webhook: invalid signature")
        return JsonResponse({'error': 'Invalid signature'}, status=400)
    
    # Handle payment success
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']

        try:
            payment = Payment.objects.get(stripe_payment_intent_id=payment_intent['id'])
            if payment.status != PaymentStatus.SUCCEEDED:
                charges = payment_intent.get('charges', {}).get('data', [])
                charge_id = charges[0]['id'] if charges else ''
                _mark_payment_succeeded(payment, charge_id, source='webhook')

        except Payment.DoesNotExist:
            logger.error(f"Stripe webhook: payment not found for intent {payment_intent['id']}")

    # Handle payment failure
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']

        try:
            payment = Payment.objects.get(stripe_payment_intent_id=payment_intent['id'])

            error_msg = payment_intent.get('last_payment_error', {}).get('message', 'Unknown error')
            payment.status = PaymentStatus.FAILED
            payment.error_message = error_msg
            payment.webhook_received = True
            payment.webhook_received_at = timezone.now()
            payment.save()

            logger.warning(f"Payment failed for intent {payment_intent['id']}: {error_msg}")

        except Payment.DoesNotExist:
            logger.error(f"Stripe webhook: payment not found for intent {payment_intent['id']}")

    return JsonResponse({'status': 'success'})


# ──────────────────────────────────────────────────────────────────
# DISPUTE VIEWS
# ──────────────────────────────────────────────────────────────────

@login_required
def open_dispute(request, order_id):
    """Buyer opens dispute for order."""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    
    # Check if order is eligible for dispute (delivered)
    if order.status not in [OrderStatus.DELIVERED, OrderStatus.SHIPPED]:
        messages.error(request, _('You can only open disputes for delivered or shipped orders.'))
        return redirect('olretail:order_detail', order_id=order.id)
    
    # Check if dispute already exists
    if hasattr(order, 'dispute'):
        messages.warning(request, _('A dispute is already open for this order.'))
        return redirect('olretail:dispute_detail', dispute_id=order.dispute.id)
    
    if request.method == 'POST':
        form = DisputeForm(request.POST)
        if form.is_valid():
            dispute = form.save(commit=False)
            dispute.order = order
            dispute.buyer = request.user
            dispute.seller = order.seller
            dispute.save()
            
            messages.success(request, _('Dispute opened. Seller has 3 days to respond.'))
            return redirect('olretail:dispute_detail', dispute_id=dispute.id)
    else:
        form = DisputeForm()
    
    context = {
        'form': form,
        'order': order,
    }
    return render(request, 'olretail/open_dispute.html', context)


@login_required
def dispute_detail(request, dispute_id):
    """View dispute detail."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    
    # Check permissions
    is_buyer = dispute.buyer == request.user
    is_seller = dispute.seller.user == request.user
    is_admin = request.user.is_staff
    
    if not (is_buyer or is_seller or is_admin):
        messages.error(request, _('You do not have permission to view this dispute.'))
        return redirect('olretail:index')
    
    deadline_passed = timezone.now() > dispute.seller_response_deadline
    context = {
        'dispute': dispute,
        'is_buyer': is_buyer,
        'is_seller': is_seller,
        'is_admin': is_admin,
        'deadline_passed': deadline_passed,
    }
    if is_seller and dispute.status == DisputeStatus.OPEN and not dispute.seller_response and not deadline_passed:
        context['form'] = SellerDisputeResponseForm()
    return render(request, 'olretail/dispute_detail.html', context)


@login_required
@require_POST
def seller_respond_dispute(request, dispute_id):
    """Seller responds to dispute."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    
    try:
        seller = request.user.seller
        if dispute.seller != seller:
            messages.error(request, _('Permission denied.'))
            return redirect('olretail:index')
    except Seller.DoesNotExist:
        messages.error(request, _('You must be a seller to respond to disputes.'))
        return redirect('olretail:index')
    
    # Check deadline
    if timezone.now() > dispute.seller_response_deadline:
        messages.error(request, _('Response deadline has passed.'))
        return redirect('olretail:dispute_detail', dispute_id=dispute.id)
    
    form = SellerDisputeResponseForm(request.POST)
    if form.is_valid():
        dispute.seller_response = form.cleaned_data['seller_response']
        dispute.status = DisputeStatus.SELLER_RESPONSE
        dispute.save()
        
        messages.success(request, _('Your response has been submitted.'))
        return redirect('olretail:dispute_detail', dispute_id=dispute.id)
    
    context = {
        'dispute': dispute,
        'form': form,
    }
    return render(request, 'olretail/seller_respond_dispute.html', context)


# ──────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ──────────────────────────────────────────────────────────────────

@login_required
def notifications(request):
    """Full notification list — the header bell only shows the most recent
    few (see context_processors.notifications)."""
    notification_list = Notification.objects.filter(recipient=request.user).select_related('order')[:100]
    return render(request, 'olretail/notifications.html', {'notification_list': notification_list})


@login_required
def notification_open(request, pk):
    """Mark one notification read and send the user to what it's about."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])
    if notification.order_id:
        return redirect('olretail:order_detail', order_id=notification.order_id)
    return redirect('olretail:notifications')


@login_required
@require_POST
def notifications_mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect(request.POST.get('next') or 'olretail:notifications')
