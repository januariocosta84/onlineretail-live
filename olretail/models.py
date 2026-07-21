from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# Stored values stay in English for data compatibility; labels are translated.
CONDITION_CHOICES = (
    ("New", _("New")),
    ("Second Hand", _("Second Hand")),
)


class CourierVerificationStatus(models.TextChoices):
    PENDING = "pending", _("Pending Verification")
    VERIFIED = "verified", _("Verified")
    REJECTED = "rejected", _("Rejected")


class Buyer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=255)
    mobile = models.CharField(max_length=40)

    @property
    def get_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def get_id(self):
        return self.user.id

    def __str__(self):
        return self.get_name


class Courier(models.Model):
    """Delivery person/company. Granted by admin (see accounts/roles.py) —
    not self-registerable, since it carries the ability to confirm delivery."""

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=255, blank=True)
    mobile = models.CharField(max_length=40)
    service_cities = models.ManyToManyField(
        "City",
        blank=True,
        related_name="couriers",
        help_text=_(
            "Cities this courier delivers to. Leave empty if not yet configured "
            "(order dropdowns will show all couriers until this is set)."
        ),
    )
    id_document = models.ImageField(upload_to="courier_ids/", null=True, blank=True)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    verification_status = models.CharField(
        max_length=20,
        choices=CourierVerificationStatus.choices,
        default=CourierVerificationStatus.PENDING,
    )
    # Admin's reason when rejecting — mirrors Product.moderation_note.
    verification_note = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="couriers_verified"
    )

    @property
    def get_name(self):
        return self.user.get_full_name() or self.user.username

    def __str__(self):
        return self.get_name


class SellerType(models.TextChoices):
    INDIVIDUAL = "individual", _("Individual")
    COMPANY = "company", _("Company")
    RESTAURANT = "restaurant", _("Restaurant")


class SellerVerificationStatus(models.TextChoices):
    PENDING = "pending", _("Pending Verification")
    VERIFIED = "verified", _("Verified")
    REJECTED = "rejected", _("Rejected")


class Seller(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=255)
    mobile = models.CharField(max_length=40)
    payment_instructions = models.TextField(
        blank=True,
        help_text=_(
            "Bank or mobile money details buyers use to pay you directly "
            "(e.g. bank name, account number, account holder name)."
        ),
    )
    seller_type = models.CharField(
        max_length=20, choices=SellerType.choices, default=SellerType.INDIVIDUAL,
    )
    # Only populated for SellerType.COMPANY and SellerType.RESTAURANT —
    # collected at registration, and editable afterward on the seller
    # payment-settings page.
    company_name = models.CharField(max_length=200, blank=True)
    company_tin = models.CharField(max_length=50, blank=True, verbose_name="TIN")
    company_address = models.CharField(max_length=255, blank=True)
    company_bank_account = models.CharField(max_length=100, blank=True)
    # The business's legally responsible person — same COMPANY/RESTAURANT-only
    # scope as the company_* fields above.
    director_name = models.CharField(max_length=200, blank=True)
    director_id_number = models.CharField(max_length=50, blank=True, verbose_name="Director ID / TIN Number")
    director_phone = models.CharField(max_length=40, blank=True)
    director_email = models.EmailField(blank=True)
    # Business verification — a trust badge for buyers, not a gate: an
    # unverified company can still sell and get paid exactly the same as a
    # verified one (contrast Courier.verification_status, which does gate
    # delivery assignment).
    business_document = models.ImageField(upload_to="seller_business_docs/", null=True, blank=True)
    verification_status = models.CharField(
        max_length=20, choices=SellerVerificationStatus.choices, default=SellerVerificationStatus.PENDING,
    )
    verification_note = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="sellers_verified"
    )

    @property
    def get_name(self):
        # Company and Restaurant sellers trade under their business name
        # everywhere they're shown as "the seller" — product listings, order
        # confirmations, payouts, etc. — not the individual account holder's
        # personal name.
        if self.seller_type in (SellerType.COMPANY, SellerType.RESTAURANT) and self.company_name:
            return self.company_name
        return self.user.get_full_name() or self.user.username

    @property
    def get_id(self):
        return self.user.id

    @property
    def is_verified_business(self):
        return (
            self.seller_type in (SellerType.COMPANY, SellerType.RESTAURANT)
            and self.verification_status == SellerVerificationStatus.VERIFIED
        )

    @property
    def whatsapp_number(self):
        """Mobile number in international digits-only form for wa.me links.

        Numbers are stored as typed by sellers (usually the 7/8-digit local
        format); WhatsApp requires country code with no +, spaces or zeros,
        so local numbers get Timor-Leste's 670 prefix.
        """
        digits = "".join(c for c in self.mobile if c.isdigit()).lstrip("0")
        if not digits:
            return ""
        if not digits.startswith("670"):
            digits = "670" + digits
        return digits

    def __str__(self):
        return self.get_name


class MenuCategory(models.Model):
    """A restaurant's own menu sections (Breakfast, Lunch, Drinks, ...) —
    distinct from the site-wide Category taxonomy below, which is a shared
    list every seller picks a single entry from. A MenuCategory belongs to
    one restaurant Seller and only they can assign their products to it."""

    seller = models.ForeignKey(Seller, on_delete=models.CASCADE, related_name="menu_categories")
    name = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        unique_together = ("seller", "name")
        verbose_name_plural = "Menu categories"

    def __str__(self):
        return self.name


class Country(models.Model):
    country = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["country"]
        verbose_name_plural = "Countries"

    def __str__(self):
        return self.country


class City(models.Model):
    city = models.CharField(max_length=100, unique=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    # Flat delivery fee for orders delivered to this city — city-based like
    # Courier.service_cities, not coordinate-based (no maps/geocoding here).
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        ordering = ["city"]
        verbose_name_plural = "Cities"

    def __str__(self):
        return self.city


class Category(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["title"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return f"{reverse('olretail:index')}?category={self.slug}"


# Categories that are contact-the-seller-only: big-ticket or service items
# (viewings, financing, scheduling, etc. happen off-platform) that don't fit
# a cart/checkout flow. Matched by slug, not title, since Category.title is
# translated and slugs aren't.
NON_CART_CATEGORY_SLUGS = {"housing", "vehicles", "motorcycles", "services"}

# Services have no physical stock or condition — matched by slug, not title,
# for the same reason as above.
SERVICE_CATEGORY_SLUG = "services"

# Restaurant menu items, like services, have no "condition" (new/second-hand)
# or traditional stock count — Product.is_available is their analog. Unlike
# services, restaurant items ARE cart-purchasable (not in
# NON_CART_CATEGORY_SLUGS). This is a dedicated Category row, distinct from
# the pre-existing "food" category already used by ordinary grocery listings.
RESTAURANT_CATEGORY_SLUG = "restaurant"

# Categories where quantity/condition don't apply and are hidden on the
# product form in favor of category-specific fields instead.
NO_CONDITION_QUANTITY_CATEGORY_SLUGS = {SERVICE_CATEGORY_SLUG, RESTAURANT_CATEGORY_SLUG}


class ProductStatus(models.TextChoices):
    PENDING = "pending", _("Pending approval")
    APPROVED = "approved", _("Published")
    CHANGES_REQUESTED = "changes", _("Changes requested")
    REJECTED = "rejected", _("Rejected")
    SUSPENDED = "suspended", _("Suspended")


class Product(models.Model):
    IMAGE_FIELD_NAMES = ("product_image", "product_image_2", "product_image_3")

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    product_image = models.ImageField(upload_to="product_image", null=True, blank=True)
    product_image_2 = models.ImageField(upload_to="product_image", blank=True)
    product_image_3 = models.ImageField(upload_to="product_image", blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=13, decimal_places=2)
    description = models.TextField()
    # Translatable marketing/content fields beyond the core name/description —
    # all optional in every language (see olretail/translation.py).
    short_description = models.CharField(
        max_length=300, blank=True, help_text=_("A one-line summary shown in listings.")
    )
    specifications = models.TextField(
        blank=True, help_text=_('One per line, e.g. "Weight: 500g".')
    )
    features = models.TextField(blank=True, help_text=_('One per line, e.g. "Hand-woven".'))
    seo_title = models.CharField(
        max_length=70,
        blank=True,
        help_text=_("Optional — shown in search engine results instead of the product name."),
    )
    seo_description = models.CharField(
        max_length=160,
        blank=True,
        help_text=_("Optional — shown in search engine results instead of the description."),
    )
    tags = models.CharField(
        max_length=255, blank=True, help_text=_('Optional — comma-separated, e.g. "scarf, wool, winter".')
    )
    country = models.ForeignKey(Country, on_delete=models.PROTECT)
    item_location = models.ForeignKey(City, on_delete=models.PROTECT)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    quantity = models.PositiveIntegerField()
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=12,
        choices=ProductStatus.choices,
        default=ProductStatus.PENDING,
        db_index=True,
    )
    # Reason given by an administrator when rejecting / requesting changes /
    # suspending; shown to the seller on their dashboard.
    moderation_note = models.TextField(blank=True)
    featured = models.BooleanField(default=False)
    condition = models.CharField(max_length=40, choices=CONDITION_CHOICES, default="New")
    # Packaging details — all optional since they don't apply to every
    # product (e.g. a single electronics item has no "box").
    size = models.CharField(max_length=50, blank=True, help_text=_("e.g. L, 42, 500ml"))
    pieces_per_unit = models.PositiveIntegerField(
        null=True, blank=True, help_text=_("e.g. 12 pens in a pack")
    )
    units_per_box = models.PositiveIntegerField(
        null=True, blank=True, help_text=_("e.g. 24 packs in a box")
    )
    # Restaurant menu items only — a restaurant's own menu section (Breakfast,
    # Drinks, ...), on/off availability instead of a stock count, and prep time.
    menu_category = models.ForeignKey(
        MenuCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    is_available = models.BooleanField(default=True)
    prep_time_minutes = models.PositiveIntegerField(
        null=True, blank=True, help_text=_("e.g. 20")
    )

    class Meta:
        ordering = ["-created"]

    def save(self, *args, **kwargs):
        if not self.slug or (self.pk is None):
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        base = slugify(self.name)[:200] or "product"
        slug = base
        counter = 2
        qs = Product.objects.exclude(pk=self.pk) if self.pk else Product.objects.all()
        while qs.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    def get_absolute_url(self):
        return reverse("olretail:details", kwargs={"slug": self.slug})

    @property
    def approved(self):
        """Backward-compatible alias used throughout the templates."""
        return self.status == ProductStatus.APPROVED

    @property
    def in_stock(self):
        return self.quantity > 0

    @property
    def cart_purchasable(self):
        """False for categories that must be arranged directly with the
        seller (housing, vehicles, motorcycles, services) — no cart/checkout."""
        return self.category_id is not None and self.category.slug not in NON_CART_CATEGORY_SLUGS

    @property
    def is_service_category(self):
        """True for service listings, which have no physical stock or
        condition to show (quantity/condition are just placeholder defaults)."""
        return self.category_id is not None and self.category.slug == SERVICE_CATEGORY_SLUG

    @property
    def is_restaurant_category(self):
        return self.category_id is not None and self.category.slug == RESTAURANT_CATEGORY_SLUG

    @property
    def available_for_purchase(self):
        """Whether there's currently stock/availability to buy — restaurant
        menu items use the is_available toggle (no real stock count),
        everything else uses the tracked quantity."""
        return self.is_available if self.is_restaurant_category else self.in_stock

    @property
    def hides_quantity_condition(self):
        """True for categories where quantity/condition are meaningless
        (services and restaurant menu items) and are hidden on the product
        form/detail page in favor of category-specific fields instead."""
        return (
            self.category_id is not None
            and self.category.slug in NO_CONDITION_QUANTITY_CATEGORY_SLUGS
        )

    @property
    def gallery(self):
        """Non-empty extra images for the detail page."""
        return [img for img in (self.product_image_2, self.product_image_3) if img]

    def __str__(self):
        return self.name


@receiver(pre_delete, sender=Product)
def _delete_product_images(sender, instance, **kwargs):
    """Deleting a Product row doesn't automatically remove its uploaded
    image files from disk (Django's default behavior) — clean them up here
    so a delete doesn't leave orphaned files taking up server storage.
    A signal (not an overridden .delete()) so this fires for every deletion
    path: a seller deleting their own listing, an admin's permanent
    removal, and bulk QuerySet deletes (e.g. seed_demo_users --reset)."""
    for name in Product.IMAGE_FIELD_NAMES:
        field = getattr(instance, name)
        if field:
            field.delete(save=False)


class SentimentLabel(models.TextChoices):
    POSITIVE = "positive", _("Positive")
    NEUTRAL = "neutral", _("Neutral")
    NEGATIVE = "negative", _("Negative")


class Comment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="comments")
    commenter_name = models.CharField(max_length=200)
    body = models.TextField()
    date_added = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=True)  # moderators can hide comments
    sentiment = models.CharField(
        max_length=10,
        choices=SentimentLabel.choices,
        default=SentimentLabel.NEUTRAL,
        db_index=True,
    )
    sentiment_score = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-date_added"]

    def save(self, *args, **kwargs):
        from .sentiment import analyze

        self.sentiment, self.sentiment_score = analyze(self.body)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product} - {self.commenter_name}"


# Re-exported so Django's app registry (and makemigrations) discovers them —
# they live in payment_models.py to keep the marketplace and payment domains separate.
from .payment_models import (  # noqa: E402, F401
    Cart, Order, OrderStatus, FoodOrderStatus, PaymentMethod, Payment, PaymentStatus, Transaction,
    TransactionType, SellerBalance, Payout, PayoutStatus, Dispute,
    DisputeStatus, DisputeResolution, DisputeReason, DeliveryUpdate, PlatformSettings,
    Notification, Rating, CourierRating, Wishlist,
)
from .subscription_models import (  # noqa: E402, F401
    FREE_PRODUCT_LIMIT, PLAN_PRICES, PLAN_DURATION_DAYS, SubscriptionPlan,
    SellerSubscription, SubscriptionRequest, SubscriptionRequestStatus,
)
from .banking_models import (  # noqa: E402, F401
    VirtualAccountStatus, ForcedOutcome, VirtualBankAccount, SimulatedOutcome,
    SimulatedBankTransaction, GatewayEventLog, IdempotencyRecord,
)
