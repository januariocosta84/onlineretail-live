from django.conf import settings

from .models import Cart, Category, Notification, Wishlist


def platform_fee(request):
    """Commission rate as a display-ready percent string, so templates
    never hardcode a number that drifts from settings.COMMISSION_RATE
    (e.g. checkout.html, cart.html, order_detail.html, payment.html,
    seller_balance.html all quote the rate in prose). This is a fee the
    *buyer* pays on top of the price on Bank Transfer orders — see
    _apply_order_delivered in payment_views.py, which credits the seller
    the full subtotal, and the Terms of Service's "paid by the buyer — it
    is not deducted from the seller." There used to also be a
    seller_earn_percent = 100 - rate_percent here, which was simply wrong
    (implied the platform deducted a cut from the seller); removed rather
    than fixed in place, since "100%" isn't a meaningful rate to display."""
    rate_percent = settings.COMMISSION_RATE * 100
    # "{:g}" strips a trailing .0 (2.0 -> "2") but keeps real decimals
    # (2.5 -> "2.5") if the rate is ever set to something non-whole.
    commission_rate_percent = f"{rate_percent:g}"
    return {
        "commission_rate_percent": commission_rate_percent,
    }


def categories(request):
    """Make the category list available to every template (header nav)."""
    return {"categories": Category.objects.all()}


def roles(request):
    """Expose the current user's roles so menus adapt to the account type."""
    from accounts.roles import is_buyer, is_courier, is_seller  # local import: avoid app-load cycle

    return {
        "is_buyer": is_buyer(request.user),
        "is_seller": is_seller(request.user),
        "is_courier": is_courier(request.user),
    }


def notifications(request):
    """Unread count + a short recent list for the header bell dropdown."""
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0, "recent_notifications": []}

    qs = Notification.objects.filter(recipient=request.user).select_related("order")
    return {
        "unread_notification_count": qs.filter(is_read=False).count(),
        "recent_notifications": qs[:8],
    }


def cart_count(request):
    """Item count badge on the header Cart link — counts distinct line
    items, not summed quantities, matching what the cart page itself lists."""
    if not request.user.is_authenticated:
        return {"cart_count": 0}
    return {"cart_count": Cart.objects.filter(buyer=request.user).count()}


def wishlist_count(request):
    """Item count badge on the header Wishlist link."""
    if not request.user.is_authenticated:
        return {"wishlist_count": 0}
    return {"wishlist_count": Wishlist.objects.filter(buyer=request.user).count()}
