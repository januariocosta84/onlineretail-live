import stripe
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.contrib import messages
from django.db import transaction

from olretail.models import Product, Seller, Buyer, Courier
from olretail.decorators import seller_required, courier_required
from .payment_models import (
    Cart, Order, Payment, OrderStatus, PaymentMethod, PaymentStatus, Transaction,
    TransactionType, SellerBalance, Dispute, DisputeStatus, DisputeResolution, DeliveryUpdate
)
from .payment_forms import (
    CheckoutForm, DisputeForm, SellerDisputeResponseForm, SellerPaymentInstructionsForm,
    ShipOrderForm, DeliveryUpdateForm, DeliveryProofForm, SubscriptionRequestForm,
)
from .subscription_models import (
    FREE_PRODUCT_LIMIT, PLAN_PRICES, SellerSubscription, SubscriptionRequest, SubscriptionRequestStatus,
)

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

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
    
    quantity = int(request.POST.get('quantity', 1))
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
    quantity = int(request.POST.get('quantity', 1))
    
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
                delivery_phone=form.cleaned_data['delivery_phone'],
                buyer_notes=form.cleaned_data.get('buyer_notes', ''),
            )
            orders.append(order)

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

            order.product.quantity -= order.quantity
            order.product.save()

            Cart.objects.filter(buyer=order.buyer, product=order.product).delete()
            order_numbers.append(order.order_number)

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

        order.product.quantity -= order.quantity
        order.product.save()

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
    messages.success(request, _('Payment confirmed — the order is now marked as paid.'))
    return redirect('olretail:order_detail', order_id=order.id)


@seller_required
def seller_payment_settings(request):
    """Seller's bank/mobile money details shown to buyers who pay by direct transfer."""
    seller = request.user.seller
    if request.method == 'POST':
        form = SellerPaymentInstructionsForm(request.POST, instance=seller)
        if form.is_valid():
            form.save()
            messages.success(request, _('Payment details saved.'))
            return redirect('olretail:seller_payment_settings')
    else:
        form = SellerPaymentInstructionsForm(instance=seller)
    return render(request, 'olretail/seller_payment_settings.html', {'form': form})


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
            'platform_payment_instructions': settings.PLATFORM_PAYMENT_INSTRUCTIONS,
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
        context['ship_form'] = ShipOrderForm()
    if is_seller and order.status == OrderStatus.SHIPPED:
        context['delivery_update_form'] = DeliveryUpdateForm()
    if (is_seller or is_courier) and order.status == OrderStatus.SHIPPED:
        context['delivery_proof_form'] = DeliveryProofForm()
    return render(request, 'olretail/order_detail.html', context)


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

    form = ShipOrderForm(request.POST)
    if form.is_valid():
        order.status = OrderStatus.SHIPPED
        order.shipped_at = timezone.now()
        order.courier_name = form.cleaned_data['courier_name']
        order.tracking_number = form.cleaned_data['tracking_number']
        order.assigned_courier = form.cleaned_data['assigned_courier']
        order.save()
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
    }
    return render(request, 'olretail/courier_deliveries.html', context)


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
    
    context = {
        'dispute': dispute,
        'is_buyer': is_buyer,
        'is_seller': is_seller,
        'is_admin': is_admin,
        'deadline_passed': timezone.now() > dispute.seller_response_deadline,
    }
    if is_seller and dispute.status == DisputeStatus.OPEN and not dispute.seller_response:
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
