import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import (
    Avg, Count, DecimalField, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Sum,
)
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .decorators import seller_required
from .forms import CommentForm, MenuCategoryForm, ProductForm
from .models import (
    RESTAURANT_CATEGORY_SLUG,
    SERVICE_CATEGORY_SLUG,
    Category,
    FREE_PRODUCT_LIMIT,
    MenuCategory,
    Order,
    OrderStatus,
    Product,
    ProductStatus,
    Rating,
    SellerSubscription,
    SellerType,
    Wishlist,
)

logger = logging.getLogger(__name__)

PRODUCTS_PER_PAGE = 12

SORT_OPTIONS = {
    "newest": "-created",
    "price_asc": "price",
    "price_desc": "-price",
    "name": "name",
    "best_selling": "-order_count",
}

# A sale only "counts" once money has actually changed hands — excludes
# pending_payment/payment_reported (not yet paid) and cancelled/refunded.
COMPLETED_ORDER_STATUSES = [
    OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED,
]


def _with_order_count(queryset):
    """Annotate each product with its completed-order count, via a
    correlated subquery rather than a Count() join — this queryset is
    usually already annotated with avg_rating/rating_count over a different
    reverse relation (ratings), and combining multiple Count()s over
    different relations in one query fans out and corrupts both unless
    every Count is marked distinct; a subquery sidesteps that entirely."""
    order_counts = (
        Order.objects.filter(product=OuterRef("pk"), status__in=COMPLETED_ORDER_STATUSES)
        .values("product")
        .annotate(c=Count("id"))
        .values("c")
    )
    return queryset.annotate(order_count=Coalesce(Subquery(order_counts, output_field=IntegerField()), 0))


def _parse_price(raw):
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def index(request):
    """Catalog: approved products with category filter, search and sorting."""
    products = Product.objects.filter(status=ProductStatus.APPROVED).select_related(
        "category", "item_location", "country", "seller__user"
    ).annotate(avg_rating=Avg("ratings__score"), rating_count=Count("ratings"))

    active_category = None
    category_slug = request.GET.get("category")
    if category_slug:
        active_category = Category.objects.filter(slug=category_slug).first()
        if active_category:
            products = products.filter(category=active_category)
        else:
            messages.warning(request, _("That category does not exist."))

    query = (request.GET.get("q") or request.GET.get("search") or "").strip()
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    min_price = _parse_price(request.GET.get("min_price"))
    if min_price is not None:
        products = products.filter(price__gte=min_price)
    max_price = _parse_price(request.GET.get("max_price"))
    if max_price is not None:
        products = products.filter(price__lte=max_price)

    sort = request.GET.get("sort", "newest")
    if sort == "best_selling":
        products = _with_order_count(products)
    products = products.order_by(SORT_OPTIONS.get(sort, "-created"))

    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Preserve filters across pagination links.
    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    # Admin-featured products headline the carousel; fall back to the page.
    featured = [
        p
        for p in Product.objects.filter(status=ProductStatus.APPROVED, featured=True)
        .exclude(product_image="")[:3]
        if p.product_image
    ] or [p for p in page_obj.object_list if p.product_image][:3]

    # Best sellers is a merchandising section on the plain default view only
    # (same condition the featured carousel already uses) — a search/
    # category/filtered view is the buyer already narrowing down, showing
    # unrelated best sellers there would be noise.
    best_sellers = []
    if not query and not active_category and not min_price and not max_price:
        best_sellers = list(
            _with_order_count(
                Product.objects.filter(status=ProductStatus.APPROVED)
                .select_related("category", "item_location", "country", "seller__user")
                .annotate(avg_rating=Avg("ratings__score"), rating_count=Count("ratings"))
            )
            .filter(order_count__gt=0)
            .order_by("-order_count")[:8]
        )

    wishlisted_product_ids = set()
    if request.user.is_authenticated:
        shown_ids = [p.id for p in page_obj.object_list] + [p.id for p in best_sellers]
        wishlisted_product_ids = set(
            Wishlist.objects.filter(buyer=request.user, product_id__in=shown_ids).values_list("product_id", flat=True)
        )

    return render(
        request,
        "olretail/index.html",
        {
            "page_obj": page_obj,
            "paginator": paginator,
            "active_category": active_category,
            "query": query,
            "sort": sort,
            "min_price": request.GET.get("min_price", ""),
            "max_price": request.GET.get("max_price", ""),
            "querystring": querystring,
            "featured": featured,
            "best_sellers": best_sellers,
            "wishlisted_product_ids": wishlisted_product_ids,
            "result_count": paginator.count,
        },
    )


def about(request):
    """Public 'About Us' page — who TimorMart is and what the platform offers."""
    return render(request, "olretail/about.html")


def search(request):
    """Legacy /search/ endpoint — same catalog view, kept for old links."""
    return index(request)


def category_redirect(request, id):
    """Legacy /category/<id> endpoint — redirect to the filtered catalog."""
    category = get_object_or_404(Category, id=id)
    return redirect(f"/?category={category.slug}")


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "item_location", "country", "seller__user"),
        slug=slug,
    )
    from accounts.roles import is_seller as user_is_seller

    is_owner = user_is_seller(request.user) and product.seller_id == request.user.seller.id
    if not product.approved and not (is_owner or request.user.is_staff):
        # Unapproved listings are only visible to their owner and staff.
        messages.info(request, _("That product is awaiting approval."))
        return redirect("olretail:index")

    # Commenting is a buyer capability (role-based access control).
    from accounts.roles import is_buyer

    can_comment = is_buyer(request.user)

    if request.method == "POST":
        if not can_comment:
            messages.error(request, _("Only buyer accounts can post comments."))
            return redirect(f"{product.get_absolute_url()}#comments")
        comment_form = CommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.product = product
            comment.save()
            messages.success(request, _("Your comment was posted."))
            return redirect(f"{product.get_absolute_url()}#comments")
        messages.error(request, _("Please correct the errors in your comment."))
    else:
        initial = {}
        if request.user.is_authenticated:
            initial["commenter_name"] = request.user.get_full_name() or request.user.username
        comment_form = CommentForm(initial=initial)

    related = (
        Product.objects.filter(status=ProductStatus.APPROVED, category=product.category)
        .exclude(pk=product.pk)
        .select_related("category")[:4]
    )

    gallery_urls = [
        img.url
        for img in (product.product_image, product.product_image_2, product.product_image_3)
        if img
    ]

    # Contact details are restricted to buyer-capable accounts. The number and
    # WhatsApp link are only put into the template context (and therefore the
    # HTML) when authorized — this is backend enforcement, not CSS hiding.
    can_view_contact = is_buyer(request.user) or is_owner or request.user.is_staff

    whatsapp_url = ""
    if can_view_contact and product.seller.whatsapp_number:
        wa_text = _("Hello, I am interested in “%(name)s” (%(url)s) on TimorMart.") % {
            "name": product.name,
            "url": request.build_absolute_uri(product.get_absolute_url()),
        }
        whatsapp_url = f"https://wa.me/{product.seller.whatsapp_number}?text={quote(wa_text)}"

    public_comments = product.comments.filter(is_public=True)
    sentiment_counts = {
        "positive": public_comments.filter(sentiment="positive").count(),
        "negative": public_comments.filter(sentiment="negative").count(),
    }

    rating_stats = product.ratings.aggregate(avg=Avg("score"), count=Count("id"))
    # Written reviews are optional on a Rating — only show ones with text.
    # Every Rating is already tied to a Delivered order the buyer placed, so
    # these are inherently verified-purchase reviews, no separate gating.
    reviews = (
        product.ratings.exclude(review_text="")
        .select_related("buyer")
        .order_by("-created_at")[:20]
    )

    # A restaurant's rating is just an aggregate over the same Rating table,
    # scoped to every product (menu item) under that seller — no separate
    # model needed.
    restaurant_rating_stats = None
    if product.is_restaurant_category:
        restaurant_rating_stats = Rating.objects.filter(product__seller=product.seller).aggregate(
            avg=Avg("score"), count=Count("id")
        )

    return render(
        request,
        "olretail/details.html",
        {
            "product": product,
            "details": product,  # backward-compat alias
            "comments": public_comments,
            "sentiment_counts": sentiment_counts,
            "comment_form": comment_form,
            "related": related,
            "is_owner": is_owner,
            "whatsapp_url": whatsapp_url,
            "can_comment": can_comment,
            "can_view_contact": can_view_contact,
            "can_add_to_cart": (
                can_comment and not is_owner and product.approved
                and product.cart_purchasable and product.available_for_purchase
            ),
            "is_wishlisted": (
                request.user.is_authenticated
                and Wishlist.objects.filter(buyer=request.user, product=product).exists()
            ),
            "gallery_urls": gallery_urls,
            "reviews": reviews,
            "avg_rating": rating_stats["avg"],
            "rating_count": rating_stats["count"],
            "restaurant_rating_stats": restaurant_rating_stats,
            # "Seller" reads oddly for the Services category — nobody buying a
            # haircut or a repair job thinks of the person doing it as a
            # "seller". The template swaps in "service provider" wording,
            # and also hides the condition/quantity badges, when this is set.
            "is_service_category": product.is_service_category,
        },
    )


@seller_required
def seller_dashboard(request):
    seller = request.user.seller
    products = seller.product_set.select_related("category", "item_location").order_by("-created")

    totals = products.aggregate(
        inventory_value=Sum(
            ExpressionWrapper(
                F("price") * F("quantity"),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )
        )
    )

    subscription, _created = SellerSubscription.objects.get_or_create(seller=seller)

    return render(
        request,
        "olretail/lista.html",
        {
            "product_list": products,
            "count": products.count(),
            "approved_count": products.filter(status=ProductStatus.APPROVED).count(),
            "pending_count": products.exclude(status=ProductStatus.APPROVED).count(),
            "inventory_value": totals["inventory_value"] or 0,
            "subscription": subscription,
            "free_limit": FREE_PRODUCT_LIMIT,
        },
    )


@seller_required
def product_create(request):
    seller = request.user.seller
    subscription, _created = SellerSubscription.objects.get_or_create(seller=seller)
    if not subscription.can_post_product():
        messages.warning(
            request,
            _(
                "You've reached the free plan's %(limit)d listing limit. "
                "Subscribe to post more products."
            )
            % {"limit": FREE_PRODUCT_LIMIT},
        )
        return redirect("olretail:seller_subscription")

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, seller=seller)
        if form.is_valid():
            product = form.save(commit=False)
            product.seller = seller
            if subscription.is_paid_active:
                # Subscribers publish immediately — only free-tier listings
                # go through the admin approval queue.
                product.status = ProductStatus.APPROVED
            product.save()
            if product.status == ProductStatus.APPROVED:
                messages.success(
                    request, _("“%(name)s” was published.") % {"name": product.name}
                )
            else:
                messages.success(
                    request,
                    _("“%(name)s” was created and is awaiting approval by the administrators.")
                    % {"name": product.name},
                )
            return redirect("olretail:list")
        messages.error(request, _("Please correct the errors below."))
    else:
        form = ProductForm(seller=seller)
    return render(
        request,
        "olretail/product_form.html",
        {
            "form": form,
            "title": _("Add a new product"),
            "submit_label": _("Create product"),
            "subscription": subscription,
            "service_category_ids": list(
                Category.objects.filter(slug=SERVICE_CATEGORY_SLUG).values_list("id", flat=True)
            ),
            "restaurant_category_ids": list(
                Category.objects.filter(slug=RESTAURANT_CATEGORY_SLUG).values_list("id", flat=True)
            ),
            "is_restaurant_seller": seller.seller_type == SellerType.RESTAURANT,
        },
    )


@seller_required
def product_update(request, slug):
    product = get_object_or_404(Product, slug=slug, seller=request.user.seller)
    if request.method == "POST":
        # form.instance IS product — capture the old files before the form
        # binding overwrites these fields in place, so a replaced or
        # cleared image can have its old file cleaned up from disk after
        # save (Django never does this automatically; see the pre_delete
        # signal in models.py for the same gap on the delete side).
        old_images = {name: getattr(product, name) for name in Product.IMAGE_FIELD_NAMES}
        form = ProductForm(request.POST, request.FILES, instance=product, seller=product.seller)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.status in (ProductStatus.REJECTED, ProductStatus.CHANGES_REQUESTED):
                # Editing a rejected / changes-requested listing resubmits it.
                updated.status = ProductStatus.PENDING
                messages.success(
                    request,
                    _("“%(name)s” was resubmitted for approval.") % {"name": product.name},
                )
            else:
                messages.success(request, _("“%(name)s” was updated.") % {"name": product.name})
            updated.save()
            for name, old_file in old_images.items():
                new_file = getattr(updated, name)
                if old_file and old_file.name != (new_file.name if new_file else None):
                    old_file.delete(save=False)
            return redirect("olretail:list")
        messages.error(request, _("Please correct the errors below."))
    else:
        form = ProductForm(instance=product, seller=product.seller)
    return render(
        request,
        "olretail/product_form.html",
        {
            "form": form,
            "title": _("Edit “%(name)s”") % {"name": product.name},
            "submit_label": _("Save changes"),
            "product": product,
            "service_category_ids": list(
                Category.objects.filter(slug=SERVICE_CATEGORY_SLUG).values_list("id", flat=True)
            ),
            "restaurant_category_ids": list(
                Category.objects.filter(slug=RESTAURANT_CATEGORY_SLUG).values_list("id", flat=True)
            ),
            "is_restaurant_seller": product.seller.seller_type == SellerType.RESTAURANT,
        },
    )


@seller_required
@require_POST
def product_mark_sold(request, slug):
    product = get_object_or_404(Product, slug=slug, seller=request.user.seller)
    product.quantity = 0
    product.save(update_fields=["quantity", "updated"])
    messages.success(request, _("“%(name)s” is now marked as sold out.") % {"name": product.name})
    return redirect("olretail:list")


@seller_required
@require_POST
def product_delete(request, slug):
    product = get_object_or_404(Product, slug=slug, seller=request.user.seller)
    name = product.name
    try:
        product.delete()
    except ProtectedError:
        messages.error(
            request,
            _("“%(name)s” can't be deleted because it has order history — mark it sold out instead.")
            % {"name": name},
        )
        return redirect("olretail:list")
    messages.success(request, _("“%(name)s” was deleted.") % {"name": name})
    return redirect("olretail:list")


def _require_restaurant_seller(request):
    """Menu sections only make sense for restaurant sellers — every view
    below is gated by this instead of a decorator since it needs to render
    a message and redirect, not just 403."""
    seller = request.user.seller
    if seller.seller_type != SellerType.RESTAURANT:
        messages.error(request, _("Menu sections are only available for restaurant seller accounts."))
        return None
    return seller


@seller_required
def menu_categories(request):
    seller = _require_restaurant_seller(request)
    if seller is None:
        return redirect("olretail:list")

    if request.method == "POST":
        form = MenuCategoryForm(request.POST)
        if form.is_valid():
            section = form.save(commit=False)
            section.seller = seller
            section.save()
            messages.success(request, _("“%(name)s” was added to your menu.") % {"name": section.name})
            return redirect("olretail:menu_categories")
        messages.error(request, _("Please correct the errors below."))
    else:
        form = MenuCategoryForm()

    return render(
        request,
        "olretail/menu_categories.html",
        {
            "form": form,
            "sections": MenuCategory.objects.filter(seller=seller),
        },
    )


@seller_required
@require_POST
def menu_category_delete(request, pk):
    seller = _require_restaurant_seller(request)
    if seller is None:
        return redirect("olretail:list")

    section = get_object_or_404(MenuCategory, pk=pk, seller=seller)
    name = section.name
    section.delete()
    messages.success(request, _("“%(name)s” was removed from your menu.") % {"name": name})
    return redirect("olretail:menu_categories")
