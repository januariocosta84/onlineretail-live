from .models import Category, Notification


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
