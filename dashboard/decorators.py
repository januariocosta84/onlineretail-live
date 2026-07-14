from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def admin_required(view_func):
    """Restrict a view to staff users; others are redirected, never shown data."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if not request.user.is_staff:
            messages.error(request, "The admin dashboard is restricted to administrators.")
            return redirect("olretail:index")
        return view_func(request, *args, **kwargs)

    return wrapper
