import logging
from urllib.parse import quote

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .decorators import seller_required
from .forms import CommentForm, ProductForm
from .models import Category, FREE_PRODUCT_LIMIT, Product, ProductStatus, SellerSubscription

logger = logging.getLogger(__name__)

PRODUCTS_PER_PAGE = 12

SORT_OPTIONS = {
    "newest": "-created",
    "price_asc": "price",
    "price_desc": "-price",
    "name": "name",
}


def index(request):
    """Catalog: approved products with category filter, search and sorting."""
    products = Product.objects.filter(status=ProductStatus.APPROVED).select_related(
        "category", "item_location", "country", "seller__user"
    )

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

    sort = request.GET.get("sort", "newest")
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

    return render(
        request,
        "olretail/index.html",
        {
            "page_obj": page_obj,
            "paginator": paginator,
            "active_category": active_category,
            "query": query,
            "sort": sort,
            "querystring": querystring,
            "featured": featured,
            "result_count": paginator.count,
        },
    )


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
                and product.in_stock and product.cart_purchasable
            ),
            "gallery_urls": gallery_urls,
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
        form = ProductForm(request.POST, request.FILES)
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
        form = ProductForm()
    return render(
        request,
        "olretail/product_form.html",
        {
            "form": form,
            "title": _("Add a new product"),
            "submit_label": _("Create product"),
            "subscription": subscription,
        },
    )


@seller_required
def product_update(request, slug):
    product = get_object_or_404(Product, slug=slug, seller=request.user.seller)
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
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
            return redirect("olretail:list")
        messages.error(request, _("Please correct the errors below."))
    else:
        form = ProductForm(instance=product)
    return render(
        request,
        "olretail/product_form.html",
        {
            "form": form,
            "title": _("Edit “%(name)s”") % {"name": product.name},
            "submit_label": _("Save changes"),
            "product": product,
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
    product.delete()
    messages.success(request, _("“%(name)s” was deleted.") % {"name": name})
    return redirect("olretail:list")
