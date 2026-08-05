"""Staff-only administration dashboard.

Separate from the buyer/seller experience: overview statistics, the product
approval workflow, product / user / comment management, CSV exports, and the
audit trail. Every state-changing action is POST-only, permission-checked,
and recorded in the AuditLog.
"""

import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.deletion import ProtectedError
from django.db.models.functions import TruncDate, TruncMonth, TruncYear
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from django.db.models import F

from accounts.roles import ROLE_BUYER, ROLE_COURIER, ROLE_SELLER, assign_role, revoke_role
from olretail.models import (
    Category, Comment, Courier, CourierAssignmentStatus, CourierBalance, CourierPayout, CourierVerificationStatus,
    Dispute, DisputeReason, DisputeResolution, DisputeStatus, FoodOrderStatus, Order, OrderStatus, PaymentMethod,
    PaymentStatus, Payout,
    PayoutStatus, PlatformBankAccount, PlatformSettings, Product,
    ProductStatus, RESTAURANT_BUSINESS_CATEGORY_SLUG, Seller, SellerBalance, SellerType, SellerVerificationStatus,
)
from olretail.payment_forms import PlatformBankAccountForm
from olretail.payouts import create_scheduled_courier_payouts, create_scheduled_payouts
from olretail.subscription_models import SellerSubscription, SubscriptionRequest, SubscriptionRequestStatus

from .decorators import FINANCE_GROUP_NAME, admin_required, finance_required
from .models import AuditLog
from .utils import log_action

PAGE_SIZE = 20

# Formula-triggering characters at the start of a CSV cell (=, +, -, @) can
# execute as a spreadsheet formula when the export is opened in Excel/Sheets
# — neutralize by prefixing with a quote, per the standard CSV-injection fix.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_safe(value):
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


REVIEW_STATUSES = (ProductStatus.PENDING, ProductStatus.CHANGES_REQUESTED)

# action -> (new status, reason required)
PRODUCT_ACTIONS = {
    "approve": (ProductStatus.APPROVED, False),
    "reject": (ProductStatus.REJECTED, True),
    "request_changes": (ProductStatus.CHANGES_REQUESTED, True),
    "suspend": (ProductStatus.SUSPENDED, False),
    "restore": (ProductStatus.PENDING, False),
}


def _monthly_series(queryset, date_field, months=6):
    """Counts per calendar month for the last `months` months (current month
    included), oldest first."""
    now = timezone.now()
    # Walk back (months - 1) calendar months from the current month.
    total = now.year * 12 + (now.month - 1) - (months - 1)
    start = now.replace(
        year=total // 12, month=total % 12 + 1, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    )
    rows = (
        queryset.filter(**{f"{date_field}__gte": start})
        .annotate(month=TruncMonth(date_field))
        .values("month")
        .annotate(n=Count("id"))
    )
    counts = {row["month"].strftime("%Y-%m"): row["n"] for row in rows}
    series = []
    cursor = start
    for _ in range(months):
        key = cursor.strftime("%Y-%m")
        series.append({"label": cursor.strftime("%b %Y"), "count": counts.get(key, 0)})
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    peak = max((item["count"] for item in series), default=0) or 1
    for item in series:
        item["pct"] = round(item["count"] * 100 / peak)
    return series


def _revenue_orders():
    """Orders that actually generated commission revenue for the platform.
    Excludes cash-on-delivery — the buyer pays the courier/seller directly
    at the door, so the platform never collects its commission on those
    (a known, accepted gap, see HANDOFF.md) — and refunded orders, since a
    refund returns the full charge, commission included, to the buyer."""
    return Order.objects.filter(paid_at__isnull=False).exclude(
        payment_method=PaymentMethod.CASH_ON_DELIVERY
    ).exclude(status=OrderStatus.REFUNDED)


def _daily_revenue_series(days=30):
    """Commission revenue per calendar day for the last `days` days (today
    included), oldest first."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        _revenue_orders().filter(paid_at__date__gte=start)
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(total=Sum("commission_amount"))
    )
    totals = {row["day"]: row["total"] or Decimal("0") for row in rows}
    series = []
    cursor = start
    for _ in range(days):
        series.append({"label": cursor.strftime("%d %b"), "total": totals.get(cursor, Decimal("0"))})
        cursor += timedelta(days=1)
    peak = max((item["total"] for item in series), default=Decimal("0")) or Decimal("1")
    for item in series:
        item["pct"] = round(float(item["total"]) * 100 / float(peak))
    return series


def _monthly_revenue_series(months=12):
    """Commission revenue per calendar month for the last `months` months
    (current month included), oldest first."""
    now = timezone.now()
    total = now.year * 12 + (now.month - 1) - (months - 1)
    start = now.replace(
        year=total // 12, month=total % 12 + 1, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    )
    rows = (
        _revenue_orders().filter(paid_at__gte=start)
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(total=Sum("commission_amount"))
    )
    totals = {row["month"].strftime("%Y-%m"): row["total"] or Decimal("0") for row in rows}
    series = []
    cursor = start
    for _ in range(months):
        key = cursor.strftime("%Y-%m")
        series.append({"label": cursor.strftime("%b %Y"), "total": totals.get(key, Decimal("0"))})
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    peak = max((item["total"] for item in series), default=Decimal("0")) or Decimal("1")
    for item in series:
        item["pct"] = round(float(item["total"]) * 100 / float(peak))
    return series


def _yearly_revenue_series(years=5):
    """Commission revenue per calendar year for the last `years` years
    (current year included), oldest first."""
    now = timezone.now()
    start_year = now.year - (years - 1)
    rows = (
        _revenue_orders().filter(paid_at__year__gte=start_year)
        .annotate(year=TruncYear("paid_at"))
        .values("year")
        .annotate(total=Sum("commission_amount"))
    )
    totals = {row["year"].year: row["total"] or Decimal("0") for row in rows}
    series = []
    for y in range(start_year, now.year + 1):
        series.append({"label": str(y), "total": totals.get(y, Decimal("0"))})
    peak = max((item["total"] for item in series), default=Decimal("0")) or Decimal("1")
    for item in series:
        item["pct"] = round(float(item["total"]) * 100 / float(peak))
    return series


@admin_required
def overview(request):
    today = timezone.localdate()
    products = Product.objects.all()
    status_counts = dict(products.values_list("status").annotate(n=Count("id")))

    buyer_ids = set(User.objects.filter(buyer__isnull=False).values_list("id", flat=True))
    seller_ids = set(User.objects.filter(seller__isnull=False).values_list("id", flat=True))

    stats = {
        "total_users": User.objects.count(),
        "total_buyers": len(buyer_ids - seller_ids),
        "total_sellers": len(seller_ids - buyer_ids),
        "total_both": len(buyer_ids & seller_ids),
        "pending": status_counts.get(ProductStatus.PENDING, 0)
        + status_counts.get(ProductStatus.CHANGES_REQUESTED, 0),
        "active_products": status_counts.get(ProductStatus.APPROVED, 0),
        "rejected_products": status_counts.get(ProductStatus.REJECTED, 0),
        "suspended_products": status_counts.get(ProductStatus.SUSPENDED, 0),
        "out_of_stock": products.filter(quantity=0).count(),
        "featured": products.filter(featured=True).count(),
        "comments": Comment.objects.count(),
        "hidden_comments": Comment.objects.filter(is_public=False).count(),
        "sentiment_positive": Comment.objects.filter(sentiment="positive").count(),
        "sentiment_neutral": Comment.objects.filter(sentiment="neutral").count(),
        "sentiment_negative": Comment.objects.filter(sentiment="negative").count(),
        "new_users_today": User.objects.filter(date_joined__date=today).count(),
        "new_products_today": products.filter(created__date=today).count(),
    }

    top_sellers = (
        Seller.objects.select_related("user")
        .annotate(
            listings=Count("product"),
            published=Count("product", filter=Q(product__status=ProductStatus.APPROVED)),
        )
        .order_by("-listings")[:5]
    )
    top_categories = Category.objects.annotate(n=Count("product")).order_by("-n")[:6]
    cat_peak = max((c.n for c in top_categories), default=0) or 1
    for c in top_categories:
        c.pct = round(c.n * 100 / cat_peak)

    return render(
        request,
        "dashboard/overview.html",
        {
            "section": "overview",
            "stats": stats,
            "product_series": _monthly_series(Product.objects.all(), "created"),
            "user_series": _monthly_series(User.objects.all(), "date_joined"),
            "top_sellers": top_sellers,
            "top_categories": top_categories,
            "recent_logs": AuditLog.objects.select_related("admin")[:8],
            "recent_pending": Product.objects.filter(status__in=REVIEW_STATUSES)
            .select_related("seller__user")[:5],
        },
    )


@finance_required
def finance_overview(request):
    """Focused landing page for the Finance Officer role: sellers with
    money ready to pay out (delivery-gated — see mark_delivered), and
    pending subscription payments. A finance-only account (see
    _is_finance_only in .decorators) only ever sees this, Payouts and
    Subscriptions — everything else in the admin dashboard redirects here."""
    eligible_balances = SellerBalance.objects.filter(
        available_balance__gt=0, available_balance__gte=F("min_payout_cents")
    )
    total_available_cents = SellerBalance.objects.aggregate(total=Sum("available_balance"))["total"] or 0
    eligible_courier_balances = CourierBalance.objects.filter(
        available_balance__gt=0, available_balance__gte=F("min_payout_cents")
    )
    stats = {
        "eligible_sellers": eligible_balances.count(),
        "total_available_dollars": total_available_cents / 100,
        "eligible_couriers": eligible_courier_balances.count(),
        "pending_subscriptions": SubscriptionRequest.objects.filter(
            status=SubscriptionRequestStatus.PENDING
        ).count(),
    }
    return render(
        request,
        "dashboard/finance_overview.html",
        {
            "section": "finance_overview",
            "stats": stats,
            "recent_delivered": Order.objects.filter(status=OrderStatus.DELIVERED)
            .select_related("seller__user", "product").order_by("-delivered_at")[:15],
            "pending_subscription_requests": SubscriptionRequest.objects.filter(
                status=SubscriptionRequestStatus.PENDING
            ).select_related("seller__user").order_by("-created_at")[:10],
        },
    )


@finance_required
def revenue(request):
    """Platform commission revenue over time, bucketed by day/month/year —
    see _revenue_orders for exactly what counts (excludes COD and refunded
    orders, since the platform never actually keeps that money)."""
    total_all_time = _revenue_orders().aggregate(total=Sum("commission_amount"))["total"] or Decimal("0")
    return render(
        request,
        "dashboard/revenue.html",
        {
            "section": "revenue",
            "total_all_time": total_all_time,
            "daily": _daily_revenue_series(),
            "monthly": _monthly_revenue_series(),
            "yearly": _yearly_revenue_series(),
        },
    )


# ── Product approval workflow ──────────────────────────────────────────


@admin_required
def queue(request):
    products = (
        Product.objects.filter(status__in=REVIEW_STATUSES)
        .select_related("seller__user", "category")
        .order_by("created")
    )
    return render(request, "dashboard/queue.html", {"section": "queue", "products": products})


@admin_required
@require_POST
def queue_bulk(request):
    action = request.POST.get("action")
    reason = (request.POST.get("reason") or "").strip()
    ids = request.POST.getlist("selected")
    products = Product.objects.filter(pk__in=ids)

    if action not in ("approve", "reject") or not products:
        messages.error(request, "Select at least one product and an action.")
        return redirect("dashboard:queue")
    if action == "reject" and not reason:
        messages.error(request, "A reason is required when rejecting products.")
        return redirect("dashboard:queue")

    names = ", ".join(products.values_list("name", flat=True)[:10])
    if action == "approve":
        count = products.update(status=ProductStatus.APPROVED, moderation_note="")
        log_action(request, "bulk_approve_products", f"{count} product(s)", names)
        messages.success(request, f"{count} product(s) approved.")
    else:
        count = products.update(status=ProductStatus.REJECTED, moderation_note=reason)
        log_action(request, "bulk_reject_products", f"{count} product(s)", f"{names} — {reason}")
        messages.success(request, f"{count} product(s) rejected.")
    return redirect("dashboard:queue")


@admin_required
def product_review(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("seller__user", "category", "country", "item_location"),
        slug=slug,
    )
    return render(
        request,
        "dashboard/review.html",
        {
            "section": "queue",
            "product": product,
            "comments": product.comments.all(),
        },
    )


@admin_required
@require_POST
def product_action(request, slug):
    product = get_object_or_404(Product, slug=slug)
    action = request.POST.get("action")
    reason = (request.POST.get("reason") or "").strip()

    if action not in PRODUCT_ACTIONS:
        messages.error(request, "Unknown action.")
        return redirect("dashboard:product_review", slug=slug)

    new_status, reason_required = PRODUCT_ACTIONS[action]
    if reason_required and not reason:
        messages.error(request, "A reason is required for this action — it is shown to the seller.")
        return redirect("dashboard:product_review", slug=slug)

    product.status = new_status
    product.moderation_note = "" if action == "approve" else reason
    product.save(update_fields=["status", "moderation_note", "updated"])
    log_action(request, f"product_{action}", product.name, reason)
    messages.success(request, f"“{product.name}”: {product.get_status_display()}.")
    return redirect("dashboard:product_review", slug=slug)


# ── Product management ─────────────────────────────────────────────────


@admin_required
def products(request):
    qs = Product.objects.select_related("seller__user", "category").order_by("-created")

    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("status") or ""
    category = request.GET.get("category") or ""
    seller = request.GET.get("seller") or ""

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if category:
        qs = qs.filter(category__slug=category)
    if seller:
        qs = qs.filter(seller_id=seller)

    if request.GET.get("export") == "csv":
        log_action(request, "export_products_csv", f"{qs.count()} rows")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="products.csv"'
        writer = csv.writer(response)
        writer.writerow(["Name", "Seller", "Category", "Price", "Quantity", "Condition", "Status", "Featured", "Created"])
        for p in qs:
            writer.writerow([_csv_safe(p.name), _csv_safe(p.seller.get_name), p.category.title, p.price,
                             p.quantity, p.condition, p.get_status_display(), p.featured, p.created.date()])
        return response

    params = request.GET.copy()
    params.pop("page", None)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/products.html",
        {
            "section": "products",
            "page_obj": page_obj,
            "querystring": params.urlencode(),
            "q": q,
            "status": status,
            "category": category,
            "seller": seller,
            "status_choices": ProductStatus.choices,
            "category_choices": Category.objects.all(),
            "seller_choices": Seller.objects.select_related("user"),
        },
    )


@admin_required
@require_POST
def product_feature(request, slug):
    product = get_object_or_404(Product, slug=slug)
    product.featured = not product.featured
    product.save(update_fields=["featured", "updated"])
    verb = "featured" if product.featured else "unfeatured"
    log_action(request, f"product_{verb}", product.name)
    messages.success(request, f"“{product.name}” {verb} on the homepage.")
    return redirect(request.POST.get("next") or "dashboard:products")


@admin_required
@require_POST
def product_remove(request, slug):
    product = get_object_or_404(Product, slug=slug)
    name = product.name
    try:
        product.delete()
    except ProtectedError:
        messages.error(
            request,
            f"“{name}” has order history on record — it can't be permanently deleted. "
            "Use “Suspend” instead to remove it from the store.",
        )
        return redirect("dashboard:products")
    log_action(request, "product_removed", name, request.POST.get("reason", ""))
    messages.success(request, f"“{name}” was permanently removed.")
    return redirect("dashboard:products")


# ── User management ────────────────────────────────────────────────────


@admin_required
def users(request):
    qs = User.objects.select_related("buyer", "seller", "courier").annotate(
        is_finance=Exists(Group.objects.filter(name=FINANCE_GROUP_NAME, user=OuterRef("pk")))
    ).order_by("-date_joined")
    q = (request.GET.get("q") or "").strip()
    role = request.GET.get("role") or ""

    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q)
            | Q(last_name__icontains=q) | Q(email__icontains=q)
        )
    if role == "buyer":
        qs = qs.filter(buyer__isnull=False, seller__isnull=True)
    elif role == "seller":
        qs = qs.filter(seller__isnull=False, buyer__isnull=True)
    elif role == "both":
        qs = qs.filter(buyer__isnull=False, seller__isnull=False)
    elif role == "courier":
        qs = qs.filter(courier__isnull=False)
    elif role == "staff":
        qs = qs.filter(is_staff=True)

    if request.GET.get("export") == "csv":
        log_action(request, "export_users_csv", f"{qs.count()} rows")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="users.csv"'
        writer = csv.writer(response)
        writer.writerow(["Username", "First name", "Last name", "Email", "Buyer", "Seller",
                         "Staff", "Active", "Joined", "Last login"])
        for u in qs:
            writer.writerow([_csv_safe(u.username), _csv_safe(u.first_name), _csv_safe(u.last_name),
                             _csv_safe(u.email), hasattr(u, "buyer"), hasattr(u, "seller"), u.is_staff,
                             u.is_active, u.date_joined.date(),
                             u.last_login.date() if u.last_login else ""])
        return response

    params = request.GET.copy()
    params.pop("page", None)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/users.html",
        {
            "section": "users",
            "page_obj": page_obj,
            "querystring": params.urlencode(),
            "q": q,
            "role": role,
        },
    )


def _guard_user_change(request, target):
    """Privilege-escalation guards shared by user actions."""
    if target == request.user:
        return "You cannot modify your own account from the dashboard."
    if target.is_superuser and not request.user.is_superuser:
        return "Only a superuser can modify another superuser."
    return None


@admin_required
@require_POST
def user_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    error = _guard_user_change(request, target)
    if error:
        messages.error(request, error)
        return redirect("dashboard:users")
    target.is_active = not target.is_active
    target.save(update_fields=["is_active"])
    verb = "activated" if target.is_active else "suspended"
    log_action(request, f"user_{verb}", target.username)
    messages.success(request, f"Account “{target.username}” {verb}.")
    return redirect("dashboard:users")


@admin_required
@require_POST
def user_reset_password(request, pk):
    """Set a user's password directly from the dashboard — reuses Django's
    own SetPasswordForm for validation, so this doesn't depend on the
    separate Django-admin permission model the way the old /admin/ link did."""
    target = get_object_or_404(User, pk=pk)
    error = _guard_user_change(request, target)
    if error:
        messages.error(request, error)
        return redirect("dashboard:users")

    form = SetPasswordForm(target, request.POST)
    if form.is_valid():
        form.save()
        log_action(request, "user_password_reset", target.username)
        messages.success(request, f"Password for “{target.username}” was reset.")
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("dashboard:users")


@admin_required
@require_POST
def user_grant_role(request, pk):
    target = get_object_or_404(User, pk=pk)
    role = request.POST.get("role")
    if role not in (ROLE_BUYER, ROLE_SELLER, ROLE_COURIER):
        messages.error(request, "Unknown role.")
        return redirect("dashboard:users")
    error = _guard_user_change(request, target)
    if error:
        messages.error(request, error)
        return redirect("dashboard:users")
    if target.is_staff:
        messages.error(request, "Administrator accounts cannot hold buyer, seller, or courier roles.")
        return redirect("dashboard:users")

    profile = getattr(target, "seller", None) or getattr(target, "buyer", None) or getattr(target, "courier", None)
    assign_role(
        target,
        role,
        address=profile.address if profile else "",
        mobile=profile.mobile if profile else "",
    )
    log_action(request, "user_role_granted", target.username, role)
    messages.success(request, f"“{target.username}” now has the {role} role.")
    return redirect("dashboard:users")


@admin_required
@require_POST
def user_revoke_role(request, pk):
    target = get_object_or_404(User, pk=pk)
    role = request.POST.get("role")
    if role not in (ROLE_BUYER, ROLE_SELLER, ROLE_COURIER):
        messages.error(request, "Unknown role.")
        return redirect("dashboard:users")
    error = _guard_user_change(request, target)
    if error:
        messages.error(request, error)
        return redirect("dashboard:users")

    if role == ROLE_SELLER and hasattr(target, "seller"):
        seller = target.seller
        if seller.product_set.exists():
            messages.error(
                request,
                f"“{target.username}” still has listed products — remove or reassign them "
                "before revoking the seller role.",
            )
            return redirect("dashboard:users")
        balance = getattr(seller, "balance", None)
        if balance and (
            balance.total_earnings or balance.total_payouts
            or balance.pending_payout or balance.available_balance
        ):
            messages.error(
                request,
                f"“{target.username}” has earnings/payout history on their account — "
                "revoking the seller role would delete that financial record.",
            )
            return redirect("dashboard:users")

    try:
        revoke_role(target, role)
    except ProtectedError:
        messages.error(
            request,
            f"“{target.username}” still has orders, transactions, disputes or payouts on "
            "record — those must be resolved before the role can be revoked.",
        )
        return redirect("dashboard:users")

    log_action(request, "user_role_revoked", target.username, role)
    messages.success(request, f"“{target.username}” no longer has the {role} role.")
    return redirect("dashboard:users")


@admin_required
@require_POST
def user_grant_finance(request, pk):
    """Add a staff account to the Finance Officer group — see
    dashboard.decorators.FINANCE_GROUP_NAME. Staff-only (buyer/seller/
    courier roles use accounts.roles.assign_role instead, which explicitly
    rejects staff users, so this is a separate, staff-side mechanism)."""
    target = get_object_or_404(User, pk=pk)
    if not target.is_staff:
        messages.error(request, "Only staff accounts can be given finance access.")
        return redirect("dashboard:users")
    error = _guard_user_change(request, target)
    if error:
        messages.error(request, error)
        return redirect("dashboard:users")

    group, _created = Group.objects.get_or_create(name=FINANCE_GROUP_NAME)
    target.groups.add(group)
    log_action(request, "user_finance_granted", target.username)
    messages.success(request, f"“{target.username}” now has finance access.")
    return redirect("dashboard:users")


@admin_required
@require_POST
def user_revoke_finance(request, pk):
    target = get_object_or_404(User, pk=pk)
    error = _guard_user_change(request, target)
    if error:
        messages.error(request, error)
        return redirect("dashboard:users")

    group, _created = Group.objects.get_or_create(name=FINANCE_GROUP_NAME)
    target.groups.remove(group)
    log_action(request, "user_finance_revoked", target.username)
    messages.success(request, f"“{target.username}” no longer has finance access.")
    return redirect("dashboard:users")


# ── Comment moderation ─────────────────────────────────────────────────


@admin_required
def comments(request):
    qs = Comment.objects.select_related("product").order_by("-date_added")
    show = request.GET.get("show") or ""
    if show == "hidden":
        qs = qs.filter(is_public=False)
    elif show == "negative":
        qs = qs.filter(sentiment="negative")
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/comments.html",
        {"section": "comments", "page_obj": page_obj, "show": show},
    )


@admin_required
@require_POST
def comment_toggle(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    comment.is_public = not comment.is_public
    comment.save(update_fields=["is_public"])
    verb = "shown" if comment.is_public else "hidden"
    log_action(request, f"comment_{verb}", f"comment #{comment.pk} on {comment.product}")
    messages.success(request, f"Comment by {comment.commenter_name} is now {verb}.")
    return redirect("dashboard:comments")


@admin_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    target = f"comment #{comment.pk} by {comment.commenter_name} on {comment.product}"
    comment.delete()
    log_action(request, "comment_deleted", target)
    messages.success(request, "Comment deleted.")
    return redirect("dashboard:comments")


# ── Audit log ──────────────────────────────────────────────────────────


@admin_required
def audit(request):
    page_obj = Paginator(
        AuditLog.objects.select_related("admin"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "dashboard/audit.html", {"section": "audit", "page_obj": page_obj})


# ── Seller payouts ─────────────────────────────────────────────────────
# Money still moves by hand (bank transfer) — this only tracks who is owed
# a payout and lets an admin record that it was sent. See HANDOFF.md.


@finance_required
def payouts(request):
    qs = Payout.objects.select_related("seller__user").order_by("-created_at")
    status = request.GET.get("status") or ""
    if status:
        qs = qs.filter(status=status)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    eligible_count = SellerBalance.objects.filter(
        available_balance__gt=0, available_balance__gte=F("min_payout_cents")
    ).count()
    return render(
        request,
        "dashboard/payouts.html",
        {
            "section": "payouts",
            "page_obj": page_obj,
            "status": status,
            "status_choices": PayoutStatus.choices,
            "eligible_count": eligible_count,
        },
    )


@finance_required
@require_POST
def payouts_run(request):
    created = create_scheduled_payouts()
    if created:
        total = sum(p.amount_cents for p in created) / 100
        log_action(request, "payouts_scheduled", f"{len(created)} payout(s)", f"${total:.2f} total")
        messages.success(request, f"Scheduled {len(created)} payout(s) totaling ${total:.2f}.")
    else:
        messages.info(request, "No sellers are currently eligible for a payout.")
    return redirect("dashboard:payouts")


@finance_required
def payout_detail(request, pk):
    payout = get_object_or_404(Payout.objects.select_related("seller__user"), pk=pk)
    return render(request, "dashboard/payout_detail.html", {"section": "payouts", "payout": payout})


@finance_required
@require_POST
def payout_action(request, pk):
    payout = get_object_or_404(Payout, pk=pk)
    action = request.POST.get("action")
    balance, _ = SellerBalance.objects.get_or_create(seller=payout.seller)

    if action == "save_details":
        payout.bank_name = request.POST.get("bank_name", "").strip()
        payout.account_number = request.POST.get("account_number", "").strip()
        payout.account_holder = request.POST.get("account_holder", "").strip()
        payout.notes = request.POST.get("notes", "").strip()
        payout.save(update_fields=["bank_name", "account_number", "account_holder", "notes"])
        log_action(request, "payout_details_updated", payout.payout_id)
        messages.success(request, "Bank details saved.")
    elif action == "mark_processing" and payout.status == PayoutStatus.SCHEDULED:
        payout.status = PayoutStatus.PROCESSING
        payout.save(update_fields=["status"])
        log_action(request, "payout_processing", payout.payout_id)
        messages.success(request, f"{payout.payout_id} marked as processing.")
    elif action == "mark_paid" and payout.status in (PayoutStatus.SCHEDULED, PayoutStatus.PROCESSING):
        payout.status = PayoutStatus.PAID
        payout.paid_date = timezone.localdate()
        payout.save(update_fields=["status", "paid_date"])
        balance.complete_payout(payout.amount_cents)
        log_action(request, "payout_paid", payout.payout_id, f"${payout.amount_dollars:.2f}")
        messages.success(request, f"{payout.payout_id} marked as paid.")
    elif action == "mark_failed" and payout.status in (PayoutStatus.SCHEDULED, PayoutStatus.PROCESSING):
        payout.status = PayoutStatus.FAILED
        payout.save(update_fields=["status"])
        balance.fail_payout(payout.amount_cents)
        log_action(request, "payout_failed", payout.payout_id, f"${payout.amount_dollars:.2f}")
        messages.warning(request, f"{payout.payout_id} marked as failed — balance returned to the seller.")
    else:
        messages.error(request, "That action isn't valid for this payout's current status.")

    return redirect("dashboard:payout_detail", pk=payout.pk)


# ── Courier payouts ─────────────────────────────────────────────────────
# Same shape as seller payouts above, for delivery-fee earnings
# (CourierBalance, credited per delivery — see
# payment_views._apply_order_delivered) instead of seller commissions.


@finance_required
def courier_payouts(request):
    qs = CourierPayout.objects.select_related("courier__user").order_by("-created_at")
    status = request.GET.get("status") or ""
    if status:
        qs = qs.filter(status=status)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    eligible_count = CourierBalance.objects.filter(
        available_balance__gt=0, available_balance__gte=F("min_payout_cents")
    ).count()
    return render(
        request,
        "dashboard/courier_payouts.html",
        {
            "section": "courier_payouts",
            "page_obj": page_obj,
            "status": status,
            "status_choices": PayoutStatus.choices,
            "eligible_count": eligible_count,
        },
    )


@finance_required
@require_POST
def courier_payouts_run(request):
    created = create_scheduled_courier_payouts()
    if created:
        total = sum(p.amount_cents for p in created) / 100
        log_action(request, "courier_payouts_scheduled", f"{len(created)} payout(s)", f"${total:.2f} total")
        messages.success(request, f"Scheduled {len(created)} courier payout(s) totaling ${total:.2f}.")
    else:
        messages.info(request, "No couriers are currently eligible for a payout.")
    return redirect("dashboard:courier_payouts")


@finance_required
def courier_payout_detail(request, pk):
    payout = get_object_or_404(CourierPayout.objects.select_related("courier__user"), pk=pk)
    return render(request, "dashboard/courier_payout_detail.html", {"section": "courier_payouts", "payout": payout})


@finance_required
@require_POST
def courier_payout_action(request, pk):
    payout = get_object_or_404(CourierPayout, pk=pk)
    action = request.POST.get("action")
    balance, _ = CourierBalance.objects.get_or_create(courier=payout.courier)

    if action == "save_details":
        payout.bank_name = request.POST.get("bank_name", "").strip()
        payout.account_number = request.POST.get("account_number", "").strip()
        payout.account_holder = request.POST.get("account_holder", "").strip()
        payout.notes = request.POST.get("notes", "").strip()
        payout.save(update_fields=["bank_name", "account_number", "account_holder", "notes"])
        log_action(request, "courier_payout_details_updated", payout.payout_id)
        messages.success(request, "Bank details saved.")
    elif action == "mark_processing" and payout.status == PayoutStatus.SCHEDULED:
        payout.status = PayoutStatus.PROCESSING
        payout.save(update_fields=["status"])
        log_action(request, "courier_payout_processing", payout.payout_id)
        messages.success(request, f"{payout.payout_id} marked as processing.")
    elif action == "mark_paid" and payout.status in (PayoutStatus.SCHEDULED, PayoutStatus.PROCESSING):
        payout.status = PayoutStatus.PAID
        payout.paid_date = timezone.localdate()
        payout.save(update_fields=["status", "paid_date"])
        balance.complete_payout(payout.amount_cents)
        log_action(request, "courier_payout_paid", payout.payout_id, f"${payout.amount_dollars:.2f}")
        messages.success(request, f"{payout.payout_id} marked as paid.")
    elif action == "mark_failed" and payout.status in (PayoutStatus.SCHEDULED, PayoutStatus.PROCESSING):
        payout.status = PayoutStatus.FAILED
        payout.save(update_fields=["status"])
        balance.fail_payout(payout.amount_cents)
        log_action(request, "courier_payout_failed", payout.payout_id, f"${payout.amount_dollars:.2f}")
        messages.warning(request, f"{payout.payout_id} marked as failed — balance returned to the courier.")
    else:
        messages.error(request, "That action isn't valid for this payout's current status.")

    return redirect("dashboard:courier_payout_detail", pk=payout.pk)


# ── Seller subscriptions ───────────────────────────────────────────────
# Free sellers are capped at FREE_PRODUCT_LIMIT listings (see
# olretail.subscription_models). Upgrading is bank-transfer-style: the
# seller pays the platform directly and reports it, an admin confirms
# receipt here before it activates — no automated billing.


@finance_required
def subscriptions(request):
    qs = SubscriptionRequest.objects.select_related("seller__user").order_by("-created_at")
    status = request.GET.get("status") or ""
    if status:
        qs = qs.filter(status=status)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/subscriptions.html",
        {
            "section": "subscriptions",
            "page_obj": page_obj,
            "status": status,
            "status_choices": SubscriptionRequestStatus.choices,
            "pending_count": SubscriptionRequest.objects.filter(
                status=SubscriptionRequestStatus.PENDING
            ).count(),
        },
    )


@finance_required
def subscription_detail(request, pk):
    sub_request = get_object_or_404(
        SubscriptionRequest.objects.select_related("seller__user"), pk=pk
    )
    subscription, _created = SellerSubscription.objects.get_or_create(seller=sub_request.seller)

    preview_expiry = preview_extended = None
    if sub_request.status == SubscriptionRequestStatus.PENDING:
        preview_expiry, preview_extended = subscription.compute_renewal(sub_request.plan, sub_request.created_at)

    return render(
        request,
        "dashboard/subscription_detail.html",
        {
            "section": "subscriptions",
            "sub_request": sub_request,
            "subscription": subscription,
            "preview_expiry": preview_expiry,
            "preview_extended": preview_extended,
        },
    )


@finance_required
@require_POST
def subscription_action(request, pk):
    sub_request = get_object_or_404(SubscriptionRequest, pk=pk)
    action = request.POST.get("action")
    reason = (request.POST.get("reason") or "").strip()

    if sub_request.status != SubscriptionRequestStatus.PENDING:
        messages.error(request, "This request has already been reviewed.")
        return redirect("dashboard:subscription_detail", pk=sub_request.pk)

    if action == "approve":
        subscription, _created = SellerSubscription.objects.get_or_create(seller=sub_request.seller)
        now = timezone.now()
        # Anchored on when the seller actually reported payment, not "now" —
        # see SellerSubscription.compute_renewal for why that distinction
        # matters (admin review can lag behind submission by days).
        new_expiry, extended = subscription.compute_renewal(sub_request.plan, sub_request.created_at)
        subscription.plan = sub_request.plan
        subscription.expires_at = new_expiry
        subscription.save(update_fields=["plan", "expires_at", "updated_at"])

        sub_request.status = SubscriptionRequestStatus.APPROVED
        sub_request.reviewed_at = now
        sub_request.reviewed_by = request.user
        sub_request.save(update_fields=["status", "reviewed_at", "reviewed_by"])

        log_action(
            request, "subscription_approved", sub_request.seller.get_name,
            f"{sub_request.get_plan_display()} — ${sub_request.amount}"
            f" ({'extended' if extended else 'activated'} to {new_expiry:%Y-%m-%d})",
        )
        if extended:
            admin_message = (
                f"Subscription confirmed for {sub_request.seller.get_name} — "
                f"extended to {new_expiry:%d %b %Y}."
            )
            seller_message = f"Your subscription has been successfully extended until {new_expiry:%d %b %Y}."
        else:
            admin_message = (
                f"Subscription confirmed for {sub_request.seller.get_name} — "
                f"active until {new_expiry:%d %b %Y}."
            )
            seller_message = f"Your subscription is now active until {new_expiry:%d %b %Y}."
        messages.success(request, admin_message)

        from olretail.payment_views import _notify
        _notify(sub_request.seller.user, seller_message)
    elif action == "reject":
        if not reason:
            messages.error(request, "A reason is required when rejecting a subscription request.")
            return redirect("dashboard:subscription_detail", pk=sub_request.pk)
        sub_request.status = SubscriptionRequestStatus.REJECTED
        sub_request.admin_notes = reason
        sub_request.reviewed_at = timezone.now()
        sub_request.reviewed_by = request.user
        sub_request.save(update_fields=["status", "admin_notes", "reviewed_at", "reviewed_by"])
        log_action(request, "subscription_rejected", sub_request.seller.get_name, reason)
        messages.warning(request, f"Subscription request from {sub_request.seller.get_name} rejected.")
    else:
        messages.error(request, "Unknown action.")

    return redirect("dashboard:subscription_detail", pk=sub_request.pk)


# ── Platform settings ──────────────────────────────────────────────────


@admin_required
def platform_settings(request):
    """Platform's own payment details — where sellers send subscription
    payments. Falls back to settings.PLATFORM_PAYMENT_INSTRUCTIONS until
    an admin sets one here."""
    settings_obj = PlatformSettings.load()
    if request.method == "POST":
        settings_obj.payment_instructions = (request.POST.get("payment_instructions") or "").strip()
        try:
            fee_dollars = Decimal(request.POST.get("courier_delivery_fee_dollars") or "0")
            if fee_dollars < 0:
                raise InvalidOperation
        except InvalidOperation:
            messages.error(request, "Courier delivery fee must be a non-negative amount.")
            return redirect("dashboard:platform_settings")
        settings_obj.courier_delivery_fee_cents = int(fee_dollars * 100)
        settings_obj.save(update_fields=["payment_instructions", "courier_delivery_fee_cents", "updated_at"])
        log_action(request, "platform_payment_instructions_updated", "")
        messages.success(request, "Payment settings saved.")
        return redirect("dashboard:platform_settings")

    return render(
        request,
        "dashboard/platform_settings.html",
        {
            "section": "platform_settings",
            "settings_obj": settings_obj,
            "bank_accounts": settings_obj.bank_accounts.all(),
            "bank_account_form": PlatformBankAccountForm(),
        },
    )


@admin_required
@require_POST
def platform_bank_account_add(request):
    settings_obj = PlatformSettings.load()
    form = PlatformBankAccountForm(request.POST)
    if form.is_valid():
        account = form.save(commit=False)
        account.settings = settings_obj
        account.save()
        log_action(request, "platform_bank_account_added", account.bank_name)
        messages.success(request, "Bank account added.")
    else:
        messages.error(request, "Please correct the errors below.")
    return redirect("dashboard:platform_settings")


@admin_required
@require_POST
def platform_bank_account_delete(request, pk):
    settings_obj = PlatformSettings.load()
    account = get_object_or_404(PlatformBankAccount, pk=pk, settings=settings_obj)
    log_action(request, "platform_bank_account_removed", account.bank_name)
    account.delete()
    messages.success(request, "Bank account removed.")
    return redirect("dashboard:platform_settings")


# ── Order courier reassignment ───────────────────────────────────────────


@login_required
@require_POST
def order_reassign_courier(request, order_id):
    """The seller-facing 'Mark as Shipped' form only offers the courier
    picker at the Paid→Shipped transition — this is the only supported way
    to correct it afterward (while still Shipped, before Delivered), and
    unlike editing the order directly in Django admin, it's audit-logged.

    Open to admins (any order) and the owning seller (their own orders only)
    — a seller needs this to recover when an assigned courier turns out to
    be unavailable, not just to wait on an admin."""
    order = get_object_or_404(Order, id=order_id)
    is_owning_seller = hasattr(request.user, 'seller') and order.seller_id == request.user.seller.id
    if not (request.user.is_staff or is_owning_seller):
        messages.error(request, "You don't have permission to reassign this order's courier.")
        return redirect("olretail:order_detail", order_id=order.id)
    if order.status != OrderStatus.SHIPPED:
        messages.error(request, "Courier can only be reassigned while an order is Shipped (not yet Delivered).")
        return redirect("olretail:order_detail", order_id=order.id)

    courier_id = request.POST.get("courier_id") or None
    # A seller submitting this only ever sees verified couriers in their
    # dropdown (see olretail.views.order_detail) — enforce that server-side
    # too, so a crafted request can't assign an unverified one. Admins keep
    # the unfiltered list.
    courier_qs = Courier.objects.all() if request.user.is_staff else Courier.objects.filter(
        verification_status=CourierVerificationStatus.VERIFIED
    )
    courier = get_object_or_404(courier_qs, pk=courier_id) if courier_id else None
    previous = order.assigned_courier
    if courier == previous:
        messages.info(request, "No change — that courier is already assigned.")
        return redirect("olretail:order_detail", order_id=order.id)

    order.assigned_courier = courier
    update_fields = ["assigned_courier"]
    # Every (re)assignment restarts the accept/reject handshake — see
    # CourierAssignmentStatus. Applies uniformly, restaurant orders
    # included (they use the same handshake now, just with
    # confirm_courier_pickup also advancing food_status — see
    # payment_views.confirm_courier_pickup).
    if courier:
        order.courier_assignment_status = CourierAssignmentStatus.AWAITING_RESPONSE
        order.courier_assigned_at = timezone.now()
    else:
        order.courier_assignment_status = ""
        order.courier_assigned_at = None
    order.courier_responded_at = None
    update_fields += ["courier_assignment_status", "courier_assigned_at", "courier_responded_at"]
    order.save(update_fields=update_fields)
    log_action(
        request, "order_courier_reassigned", order.order_number,
        f"{previous.get_name if previous else 'unassigned'} → {courier.get_name if courier else 'unassigned'}",
    )

    from olretail.payment_views import _notify
    if courier:
        _notify(courier.user, f"You've been assigned to deliver order {order.order_number}.", order=order)
    if previous:
        _notify(previous.user, f"You've been unassigned from order {order.order_number}.", order=order)

    messages.success(request, f"Courier for {order.order_number} updated.")
    return redirect("olretail:order_detail", order_id=order.id)


# ── Courier verification ─────────────────────────────────────────────────


@admin_required
def courier_verification(request):
    couriers = (
        Courier.objects.filter(verification_status=CourierVerificationStatus.PENDING)
        # Nullable ImageField: rows added via migration (or never touched)
        # can have NULL rather than "" — exclude both, not just "".
        .exclude(Q(id_document="") | Q(id_document__isnull=True))
        .select_related("user")
        .order_by("user__first_name")
    )
    return render(
        request, "dashboard/courier_verification.html", {"section": "courier_verification", "couriers": couriers}
    )


@admin_required
@require_POST
def courier_verification_action(request, pk):
    courier = get_object_or_404(Courier, pk=pk)
    action = request.POST.get("action")
    reason = (request.POST.get("reason") or "").strip()

    if action not in ("approve", "reject"):
        messages.error(request, "Unknown action.")
        return redirect("dashboard:courier_verification")
    if action == "reject" and not reason:
        messages.error(request, "A reason is required when rejecting — it is shown to the courier.")
        return redirect("dashboard:courier_verification")

    if action == "approve":
        deposit_raw = (request.POST.get("deposit_amount") or "").strip()
        if deposit_raw:
            try:
                courier.deposit_amount = Decimal(deposit_raw)
            except InvalidOperation:
                messages.error(request, "Deposit amount must be a number.")
                return redirect("dashboard:courier_verification")
        courier.verification_status = CourierVerificationStatus.VERIFIED
        courier.verification_note = ""
        courier.verified_at = timezone.now()
        courier.verified_by = request.user
        courier.save(update_fields=[
            "deposit_amount", "verification_status", "verification_note", "verified_at", "verified_by",
        ])
        log_action(request, "courier_verified", courier.get_name)
        messages.success(request, f"{courier.get_name} is now verified.")
    else:
        courier.verification_status = CourierVerificationStatus.REJECTED
        courier.verification_note = reason
        courier.save(update_fields=["verification_status", "verification_note"])
        log_action(request, "courier_rejected", courier.get_name, reason)
        messages.success(request, f"{courier.get_name}'s submission was rejected.")

    return redirect("dashboard:courier_verification")


# ── Company seller verification ──────────────────────────────────────────
# Soft trust badge only — unlike courier verification, nothing here gates
# selling or payouts; approval just turns on a "Verified Business" badge.


@admin_required
def seller_verification(request):
    sellers = (
        Seller.objects.filter(verification_status=SellerVerificationStatus.PENDING)
        .exclude(seller_type=SellerType.INDIVIDUAL)
        # Nullable ImageField: rows added via migration (or never touched)
        # can have NULL rather than "" — exclude both, not just "".
        .exclude(Q(business_document="") | Q(business_document__isnull=True))
        .select_related("user")
        .order_by("company_name")
    )
    return render(
        request, "dashboard/seller_verification.html", {"section": "seller_verification", "sellers": sellers}
    )


@admin_required
@require_POST
def seller_verification_action(request, pk):
    seller = get_object_or_404(Seller, pk=pk)
    action = request.POST.get("action")
    reason = (request.POST.get("reason") or "").strip()

    if action not in ("approve", "reject"):
        messages.error(request, "Unknown action.")
        return redirect("dashboard:seller_verification")
    if action == "reject" and not reason:
        messages.error(request, "A reason is required when rejecting — it is shown to the seller.")
        return redirect("dashboard:seller_verification")

    if action == "approve":
        seller.verification_status = SellerVerificationStatus.VERIFIED
        seller.verification_note = ""
        seller.verified_at = timezone.now()
        seller.verified_by = request.user
        seller.save(update_fields=["verification_status", "verification_note", "verified_at", "verified_by"])
        log_action(request, "seller_verified", seller.get_name)
        messages.success(request, f"{seller.get_name} is now a verified business.")
    else:
        seller.verification_status = SellerVerificationStatus.REJECTED
        seller.verification_note = reason
        seller.save(update_fields=["verification_status", "verification_note"])
        log_action(request, "seller_rejected", seller.get_name, reason)
        messages.success(request, f"{seller.get_name}'s submission was rejected.")

    return redirect("dashboard:seller_verification")


# ── Bank-transfer payment disputes ─────────────────────────────────────────
# Every bank-transfer claim (mark_payment_sent) lands here the moment the
# buyer submits it — this is the primary confirmation queue now, not a
# denial-only fallback, since only an admin can see the platform's real
# bank statement. The two legacy reasons are kept in the filter so any
# pre-existing dispute from before this change still surfaces — see
# PAYMENT_VERIFICATION.md.


@admin_required
def payment_disputes(request):
    disputes = (
        Dispute.objects.filter(
            reason__in=[
                DisputeReason.PAYMENT_CLAIM_SUBMITTED,
                DisputeReason.PAYMENT_NOT_RECEIVED,
                DisputeReason.PAYMENT_NO_RESPONSE,
            ],
            status__in=[DisputeStatus.SELLER_RESPONSE, DisputeStatus.UNDER_REVIEW],
        )
        .select_related("order", "buyer", "seller__user")
        .order_by("-created_at")
    )
    rows = []
    for d in disputes:
        rows.append({
            "dispute": d,
            # Prior claims resolved against this buyer — a cheap trust
            # signal computed from data already being generated, not a new
            # scoring system to maintain.
            "buyer_prior_unverified_claims": Dispute.objects.filter(
                buyer=d.buyer,
                reason__in=[
                    DisputeReason.PAYMENT_CLAIM_SUBMITTED,
                    DisputeReason.PAYMENT_NOT_RECEIVED,
                    DisputeReason.PAYMENT_NO_RESPONSE,
                ],
                resolution=DisputeResolution.PAYMENT_REJECTED,
            ).exclude(pk=d.pk).count(),
        })
    return render(request, "dashboard/payment_disputes.html", {"section": "payment_disputes", "rows": rows})


@admin_required
@require_POST
def payment_dispute_action(request, pk):
    """Approve = treat the buyer's claim as verified and route through the
    exact same _mark_bank_transfer_paid() a seller's own confirm click
    uses, so there is only ever one code path that actually marks a
    bank-transfer order paid — see that function's docstring. Reject =
    cancel the order; nothing to restock/refund since a bank-transfer order
    never decrements stock before reaching Paid (mirrors cancel_order)."""
    dispute = get_object_or_404(Dispute, pk=pk)
    order = dispute.order
    action = request.POST.get("action")
    note = (request.POST.get("admin_notes") or "").strip()

    if action not in ("approve", "reject"):
        messages.error(request, "Unknown action.")
        return redirect("dashboard:payment_disputes")
    if dispute.status not in (DisputeStatus.SELLER_RESPONSE, DisputeStatus.UNDER_REVIEW):
        messages.error(request, "This dispute has already been resolved.")
        return redirect("dashboard:payment_disputes")

    from olretail.payment_views import _mark_bank_transfer_paid, _notify

    if action == "approve":
        if order.status not in (OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_REPORTED):
            messages.error(request, "This order is no longer awaiting payment confirmation.")
            return redirect("dashboard:payment_disputes")
        _mark_bank_transfer_paid(order)
        dispute.resolution = DisputeResolution.PAYMENT_CONFIRMED
        outcome_message = f"An administrator confirmed your payment for order {order.order_number} — it is now marked paid."
        seller_message = f"An administrator reviewed order {order.order_number} and confirmed the buyer's payment."
        log_action(request, "payment_dispute_approved", order.order_number, note)
        messages.success(request, f"Order {order.order_number} marked as paid.")
    else:
        order.status = OrderStatus.CANCELLED
        order.save(update_fields=["status"])
        dispute.resolution = DisputeResolution.PAYMENT_REJECTED
        outcome_message = (
            f"An administrator reviewed order {order.order_number} and could not verify your payment — "
            "the order has been cancelled."
        )
        seller_message = (
            f"An administrator reviewed order {order.order_number} and cancelled it — "
            "the buyer's payment claim could not be verified."
        )
        log_action(request, "payment_dispute_rejected", order.order_number, note)
        messages.success(request, f"Order {order.order_number} cancelled.")

    dispute.status = DisputeStatus.RESOLVED
    dispute.admin_notes = note
    dispute.resolved_at = timezone.now()
    dispute.resolved_by = request.user
    dispute.save(update_fields=["status", "resolution", "admin_notes", "resolved_at", "resolved_by"])
    _notify(order.buyer, outcome_message, order=order)
    _notify(order.seller.user, seller_message, order=order)

    return redirect("dashboard:payment_disputes")


# Damage/non-delivery disputes (item not received, damaged, not as
# described, wrong item, other) — the counterpart to payment_disputes
# above, which only covers pre-delivery bank-transfer payment claims.
# Before this, a dispute here had a buyer-open / seller-respond flow but
# nothing ever closed it: no admin action existed to actually resolve one.
ORDER_DISPUTE_REASONS = [
    DisputeReason.NOT_RECEIVED,
    DisputeReason.DAMAGED,
    DisputeReason.NOT_AS_DESCRIBED,
    DisputeReason.WRONG_ITEM,
    DisputeReason.OTHER,
]


@admin_required
def order_disputes(request):
    disputes = (
        Dispute.objects.filter(
            reason__in=ORDER_DISPUTE_REASONS,
            status__in=[DisputeStatus.OPEN, DisputeStatus.SELLER_RESPONSE, DisputeStatus.UNDER_REVIEW],
        )
        .select_related("order__payment", "order__seller", "buyer", "seller__user")
        .order_by("-created_at")
    )
    return render(request, "dashboard/order_disputes.html", {"section": "order_disputes", "disputes": disputes})


@admin_required
@require_POST
def order_dispute_action(request, pk):
    """Refund only works for Cash-on-delivery-free payment methods
    TimorMart actually held money for: a real Bank Transfer (manual —
    the admin has to have actually sent the money back from TimorMart's
    real bank account first, same trust boundary
    _mark_bank_transfer_paid already relies on for confirming a payment
    in) or a lingering Simulated Bank order (automated, via the test
    gateway). Cash on Delivery was paid straight to the seller/courier —
    TimorMart never held it, so there's nothing here to refund; that has
    to be arranged directly between buyer and seller. Reshipment/no-action
    just record the decision — TimorMart doesn't orchestrate a second
    shipment itself."""
    dispute = get_object_or_404(Dispute, pk=pk)
    order = dispute.order
    action = request.POST.get("action")
    note = (request.POST.get("admin_notes") or "").strip()

    if action not in ("refund", "reshipment", "no_action"):
        messages.error(request, "Unknown action.")
        return redirect("dashboard:order_disputes")
    if dispute.status not in (DisputeStatus.OPEN, DisputeStatus.SELLER_RESPONSE, DisputeStatus.UNDER_REVIEW):
        messages.error(request, "This dispute has already been resolved.")
        return redirect("dashboard:order_disputes")

    from olretail.payment_views import (
        _notify, _process_bank_refund, _process_manual_bank_transfer_refund,
    )

    if action == "refund":
        if order.payment_method == PaymentMethod.CASH_ON_DELIVERY or not order.payment_id:
            messages.error(
                request,
                "This order was paid Cash on Delivery — TimorMart never held that money, so it can't be "
                "refunded here. Arrange this directly with the buyer/seller instead.",
            )
            return redirect("dashboard:order_disputes")
        if order.payment.status != PaymentStatus.SUCCEEDED:
            messages.error(request, "This order was never actually paid — there's nothing to refund.")
            return redirect("dashboard:order_disputes")
        try:
            if order.payment.gateway == PaymentMethod.BANK_TRANSFER:
                _process_manual_bank_transfer_refund(order.payment)
            else:
                _process_bank_refund(order.payment)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("dashboard:order_disputes")
        dispute.resolution = DisputeResolution.REFUND_FULL
        outcome_message = (
            f"An administrator reviewed your dispute for order {order.order_number} and issued a full refund."
        )
        seller_message = (
            f"An administrator reviewed a dispute for order {order.order_number} and refunded the buyer."
        )
        log_action(request, "order_dispute_refunded", order.order_number, note)
        messages.success(request, f"Order {order.order_number} refunded.")
    elif action == "reshipment":
        dispute.resolution = DisputeResolution.RESHIPMENT
        outcome_message = (
            f"An administrator reviewed your dispute for order {order.order_number} — "
            "the seller will arrange a reshipment."
        )
        seller_message = (
            f"An administrator reviewed a dispute for order {order.order_number} and asked for a "
            "reshipment — please coordinate directly with the buyer."
        )
        log_action(request, "order_dispute_reshipment", order.order_number, note)
        messages.success(request, f"Order {order.order_number} marked for reshipment.")
    else:
        dispute.resolution = DisputeResolution.CLOSED_NO_ACTION
        outcome_message = (
            f"An administrator reviewed your dispute for order {order.order_number} and closed it with no action."
        )
        seller_message = outcome_message
        log_action(request, "order_dispute_closed", order.order_number, note)
        messages.success(request, f"Dispute for order {order.order_number} closed.")

    dispute.status = DisputeStatus.RESOLVED
    dispute.admin_notes = note
    dispute.resolved_at = timezone.now()
    dispute.resolved_by = request.user
    dispute.save(update_fields=["status", "resolution", "admin_notes", "resolved_at", "resolved_by"])
    _notify(order.buyer, outcome_message, order=order)
    _notify(order.seller.user, seller_message, order=order)

    return redirect("dashboard:order_disputes")


# ── Orders (all types — restaurant food orders included) ─────────────────


@admin_required
def orders(request):
    qs = Order.objects.select_related("buyer", "seller", "product", "assigned_courier__user").order_by(
        "-created_at"
    )

    q = (request.GET.get("q") or "").strip()
    status = request.GET.get("status") or ""
    food_status = request.GET.get("food_status") or ""
    seller = request.GET.get("seller") or ""

    if q:
        qs = qs.filter(Q(order_number__icontains=q) | Q(product__name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if food_status:
        qs = qs.filter(food_status=food_status)
    if seller:
        qs = qs.filter(seller_id=seller)

    params = request.GET.copy()
    params.pop("page", None)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/orders.html",
        {
            "section": "orders",
            "page_obj": page_obj,
            "querystring": params.urlencode(),
            "q": q,
            "status": status,
            "food_status": food_status,
            "seller": seller,
            "status_choices": OrderStatus.choices,
            "food_status_choices": FoodOrderStatus.choices,
            "seller_choices": Seller.objects.select_related("user"),
        },
    )


# ── Restaurants ───────────────────────────────────────────────────────────


@admin_required
def restaurants(request):
    qs = (
        Seller.objects.filter(business_categories__slug=RESTAURANT_BUSINESS_CATEGORY_SLUG)
        .distinct()
        .select_related("user")
        .annotate(product_count=Count("product"))
        .order_by("user__first_name")
    )
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(user__username__icontains=q))

    return render(request, "dashboard/restaurants.html", {"section": "restaurants", "restaurants": qs})


# ── Business list (every non-individual seller type) ──────────────────────

NON_INDIVIDUAL_SELLER_TYPES = (
    SellerType.REGISTERED_BUSINESS, SellerType.COOPERATIVE, SellerType.GOVERNMENT, SellerType.NGO,
)
NON_INDIVIDUAL_SELLER_TYPE_CHOICES = [
    (value, label) for value, label in SellerType.choices if value != SellerType.INDIVIDUAL
]


@admin_required
def business_list(request):
    qs = (
        Seller.objects.exclude(seller_type=SellerType.INDIVIDUAL)
        .select_related("user")
        .annotate(product_count=Count("product"))
        .order_by("company_name")
    )
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(company_name__icontains=q)
            | Q(company_tin__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q)
        )
    seller_type = request.GET.get("seller_type") or ""
    if seller_type in NON_INDIVIDUAL_SELLER_TYPES:
        qs = qs.filter(seller_type=seller_type)

    params = request.GET.copy()
    params.pop("page", None)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/business_list.html",
        {
            "section": "business_list",
            "page_obj": page_obj,
            "querystring": params.urlencode(),
            "q": q,
            "seller_type": seller_type,
            "seller_type_choices": NON_INDIVIDUAL_SELLER_TYPE_CHOICES,
        },
    )


