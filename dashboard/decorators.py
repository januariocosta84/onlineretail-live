from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

# Staff sub-role: not one of accounts.roles' buyer/seller/courier profiles
# (those explicitly exclude staff users) — a Finance Officer is a staff
# account first, restricted to a subset of the dashboard second. See
# dashboard.views.user_grant_finance/user_revoke_finance for how a user
# joins/leaves this group.
FINANCE_GROUP_NAME = "Finance Officer"


def _is_finance_only(user):
    """True for a staff account that exists only to work the finance
    section — not a superuser, and not (yet) given full admin access any
    other way. Superusers stay full admins even if also in this group."""
    return user.is_staff and not user.is_superuser and user.groups.filter(name=FINANCE_GROUP_NAME).exists()


def admin_required(view_func):
    """Restrict a view to staff users; others are redirected, never shown
    data. A finance-only staff account (see _is_finance_only) is redirected
    to the Finance dashboard instead — general admin pages (products,
    users, disputes...) aren't part of what they were given access to."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if not request.user.is_staff:
            messages.error(request, "The admin dashboard is restricted to administrators.")
            return redirect("olretail:index")
        if _is_finance_only(request.user):
            messages.error(request, "Your account only has access to the Finance dashboard.")
            return redirect("dashboard:finance_overview")
        return view_func(request, *args, **kwargs)

    return wrapper


def finance_required(view_func):
    """Restrict a view to staff users — used for the finance section, which
    both full admins and finance-only accounts (see FINANCE_GROUP_NAME) can
    reach. Unlike admin_required, this never redirects a finance-only
    account away."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if not request.user.is_staff:
            messages.error(request, "The finance dashboard is restricted to administrators.")
            return redirect("olretail:index")
        return view_func(request, *args, **kwargs)

    return wrapper
