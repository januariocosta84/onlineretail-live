import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import RegistrationForm
from .roles import ROLE_BUYER, assign_role, is_buyer, is_seller

logger = logging.getLogger(__name__)


def _role_home(user):
    """Staff land on the admin dashboard, sellers on their product list,
    everyone else on the store."""
    if user.is_staff:
        return "dashboard:overview"
    return "olretail:list" if is_seller(user) else "olretail:index"


def _safe_next(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return None


def register(request):
    if request.user.is_authenticated:
        return redirect(_role_home(request.user))

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            role = form.cleaned_data["account_type"]
            with transaction.atomic():
                user = form.save()
                assign_role(
                    user,
                    role,
                    address=form.cleaned_data["address"],
                    mobile=form.cleaned_data["mobile"],
                )
            login(request, user)
            logger.info("New user registered: %s (role=%s)", user.username, role)
            if role == ROLE_BUYER:
                messages.success(
                    request,
                    _("Welcome, %(name)s! Your account is ready — happy shopping.")
                    % {"name": user.first_name},
                )
            else:
                messages.success(
                    request,
                    _("Welcome, %(name)s! Your seller account is ready.")
                    % {"name": user.first_name},
                )
            return redirect(_role_home(user))
        messages.error(request, _("Please correct the errors below."))
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def userlogin(request):
    if request.user.is_authenticated:
        return redirect(_role_home(request.user))

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            user = form.get_user()
            messages.success(
                request,
                _("Welcome back, %(name)s!") % {"name": user.first_name or user.username},
            )
            return redirect(_safe_next(request) or _role_home(user))
        messages.error(request, _("Invalid username or password."))
    else:
        form = AuthenticationForm(request)

    form.fields["username"].widget.attrs.setdefault("class", "form-control")
    form.fields["password"].widget.attrs.setdefault("class", "form-control")
    return render(request, "accounts/login.html", {"form": form})


def user_logout(request):
    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect("olretail:index")


@login_required
@require_POST
def upgrade_to_buyer(request):
    """Self-service upgrade: a seller-only account adds the Buyer role."""
    user = request.user
    if user.is_staff:
        messages.error(
            request,
            _("Administrator accounts manage the platform and cannot buy or sell products."),
        )
        return redirect("dashboard:overview")
    if is_buyer(user):
        messages.info(request, _("Your account already has the buyer role."))
    else:
        profile = getattr(user, "seller", None)
        assign_role(
            user,
            ROLE_BUYER,
            address=profile.address if profile else "",
            mobile=profile.mobile if profile else "",
        )
        logger.info("User %s self-upgraded to buyer & seller", user.username)
        messages.success(
            request,
            _("Your account is now Buyer & Seller — you can contact sellers and post comments."),
        )
    return redirect(_safe_next(request) or _role_home(user))
