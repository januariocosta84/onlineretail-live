from .models import Cart, Category, Notification, Wishlist


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
