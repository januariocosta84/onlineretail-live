"""Staff-only administration dashboard.

Separate from the buyer/seller experience: overview statistics, the product
approval workflow, product / user / comment management, CSV exports, and the
audit trail. Every state-changing action is POST-only, permission-checked,
and recorded in the AuditLog.
"""

import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from django.db.models import F

from accounts.roles import ROLE_BUYER, ROLE_COURIER, ROLE_SELLER, assign_role
from olretail.models import Category, Comment, Payout, PayoutStatus, Product, ProductStatus, Seller, SellerBalance
from olretail.payouts import create_scheduled_payouts
from olretail.subscription_models import (
    PLAN_DURATION_DAYS, SellerSubscription, SubscriptionRequest, SubscriptionRequestStatus,
)

from .decorators import admin_required
from .models import AuditLog
from .utils import log_action

PAGE_SIZE = 20

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
            writer.writerow([p.name, p.seller.get_name, p.category.title, p.price,
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
    product.delete()
    log_action(request, "product_removed", name, request.POST.get("reason", ""))
    messages.success(request, f"“{name}” was permanently removed.")
    return redirect("dashboard:products")


# ── User management ────────────────────────────────────────────────────


@admin_required
def users(request):
    qs = User.objects.select_related("buyer", "seller").order_by("-date_joined")
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
            writer.writerow([u.username, u.first_name, u.last_name, u.email,
                             hasattr(u, "buyer"), hasattr(u, "seller"), u.is_staff,
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


@admin_required
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


@admin_required
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


@admin_required
def payout_detail(request, pk):
    payout = get_object_or_404(Payout.objects.select_related("seller__user"), pk=pk)
    return render(request, "dashboard/payout_detail.html", {"section": "payouts", "payout": payout})


@admin_required
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


# ── Seller subscriptions ───────────────────────────────────────────────
# Free sellers are capped at FREE_PRODUCT_LIMIT listings (see
# olretail.subscription_models). Upgrading is bank-transfer-style: the
# seller pays the platform directly and reports it, an admin confirms
# receipt here before it activates — no automated billing.


@admin_required
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


@admin_required
def subscription_detail(request, pk):
    sub_request = get_object_or_404(
        SubscriptionRequest.objects.select_related("seller__user"), pk=pk
    )
    subscription, _created = SellerSubscription.objects.get_or_create(seller=sub_request.seller)
    return render(
        request,
        "dashboard/subscription_detail.html",
        {"section": "subscriptions", "sub_request": sub_request, "subscription": subscription},
    )


@admin_required
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
        base = subscription.expires_at if subscription.is_paid_active else now
        subscription.plan = sub_request.plan
        subscription.expires_at = base + timedelta(days=PLAN_DURATION_DAYS[sub_request.plan])
        subscription.save(update_fields=["plan", "expires_at", "updated_at"])

        sub_request.status = SubscriptionRequestStatus.APPROVED
        sub_request.reviewed_at = now
        sub_request.reviewed_by = request.user
        sub_request.save(update_fields=["status", "reviewed_at", "reviewed_by"])

        log_action(
            request, "subscription_approved", sub_request.seller.get_name,
            f"{sub_request.get_plan_display()} — ${sub_request.amount}",
        )
        messages.success(
            request,
            f"Subscription confirmed for {sub_request.seller.get_name} — "
            f"active until {subscription.expires_at:%d %b %Y}.",
        )
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
