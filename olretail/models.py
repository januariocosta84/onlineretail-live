from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# Stored values stay in English for data compatibility; labels are translated.
CONDITION_CHOICES = (
    ("New", _("New")),
    ("Second Hand", _("Second Hand")),
)


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

    @property
    def get_name(self):
        return self.user.get_full_name() or self.user.username

    def __str__(self):
        return self.get_name


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

    @property
    def get_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def get_id(self):
        return self.user.id

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


class ProductStatus(models.TextChoices):
    PENDING = "pending", _("Pending approval")
    APPROVED = "approved", _("Published")
    CHANGES_REQUESTED = "changes", _("Changes requested")
    REJECTED = "rejected", _("Rejected")
    SUSPENDED = "suspended", _("Suspended")


class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    product_image = models.ImageField(upload_to="product_image", null=True, blank=True)
    product_image_2 = models.ImageField(upload_to="product_image", blank=True)
    product_image_3 = models.ImageField(upload_to="product_image", blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=13, decimal_places=2)
    description = models.TextField()
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
    def gallery(self):
        """Non-empty extra images for the detail page."""
        return [img for img in (self.product_image_2, self.product_image_3) if img]

    def __str__(self):
        return self.name


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
    Cart, Order, OrderStatus, PaymentMethod, Payment, PaymentStatus, Transaction,
    TransactionType, SellerBalance, Payout, PayoutStatus, Dispute,
    DisputeStatus, DisputeResolution, DisputeReason, DeliveryUpdate,
)
from .subscription_models import (  # noqa: E402, F401
    FREE_PRODUCT_LIMIT, PLAN_PRICES, PLAN_DURATION_DAYS, SubscriptionPlan,
    SellerSubscription, SubscriptionRequest, SubscriptionRequestStatus,
)
