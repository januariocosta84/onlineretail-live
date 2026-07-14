from .models import Category


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
