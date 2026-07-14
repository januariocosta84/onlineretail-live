from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext as _


def seller_required(view_func):
    """Allow only users with an active seller role.

    Staff accounts administer the platform and cannot sell; they are pointed
    to the admin dashboard instead.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if request.user.is_staff:
            messages.info(
                request,
                _("Administrator accounts manage the platform and cannot buy or sell products."),
            )
            return redirect("dashboard:overview")
        if hasattr(request.user, "seller") or request.user.groups.filter(name="Seller").exists():
            return view_func(request, *args, **kwargs)
        messages.error(request, _("You need a seller account to access that page."))
        return redirect("olretail:index")

    return wrapper


def courier_required(view_func):
    """Allow only users with a courier role (granted by admin, not self-registerable)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if request.user.is_staff:
            messages.info(
                request,
                _("Administrator accounts manage the platform and cannot act as couriers."),
            )
            return redirect("dashboard:overview")
        if hasattr(request.user, "courier"):
            return view_func(request, *args, **kwargs)
        messages.error(request, _("You need a courier account to access that page."))
        return redirect("olretail:index")

    return wrapper
