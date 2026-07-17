from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import (
    Buyer, Category, City, Comment, Country, Courier, CourierRating, MenuCategory, Notification, Order, Product,
    ProductStatus, Rating, Seller,
    VirtualBankAccount, SimulatedBankTransaction, GatewayEventLog,
)

admin.site.site_header = "TimorMart administration"
admin.site.site_title = "TimorMart"
admin.site.index_title = "Store management"


@admin.register(Category)
class CategoryAdmin(TranslationAdmin):
    list_display = ["title", "slug"]
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ["title"]


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ["date_added"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "seller", "category", "price", "quantity", "condition", "status", "featured", "created"]
    list_filter = ["status", "featured", "condition", "category", "country"]
    search_fields = ["name", "description", "seller__user__username"]
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ["seller__user", "category"]
    date_hierarchy = "created"
    inlines = [CommentInline]
    actions = ["approve_products", "unapprove_products"]

    @admin.action(description="Approve selected products")
    def approve_products(self, request, queryset):
        updated = queryset.update(status=ProductStatus.APPROVED, moderation_note="")
        self.message_user(request, f"{updated} product(s) approved.")

    @admin.action(description="Move selected products back to pending")
    def unapprove_products(self, request, queryset):
        updated = queryset.update(status=ProductStatus.PENDING)
        self.message_user(request, f"{updated} product(s) moved to pending.")


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
    list_display = ["get_name", "mobile", "address", "seller_type", "company_name"]
    list_filter = ["seller_type"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "mobile", "company_name", "company_tin"]


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "seller", "display_order"]
    list_filter = ["seller"]
    search_fields = ["name", "seller__user__username"]


@admin.register(Buyer)
class BuyerAdmin(admin.ModelAdmin):
    list_display = ["get_name", "mobile", "address"]


@admin.register(Courier)
class CourierAdmin(admin.ModelAdmin):
    list_display = ["get_name", "mobile", "verification_status", "deposit_amount"]
    list_filter = ["verification_status"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "mobile"]
    filter_horizontal = ["service_cities"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_number", "buyer", "seller", "product", "status", "payment_method", "assigned_courier", "total", "created_at"]
    list_filter = ["status", "payment_method"]
    search_fields = ["order_number", "buyer__username", "seller__user__username", "product__name"]
    list_select_related = ["buyer", "seller__user", "product", "assigned_courier__user"]
    date_hierarchy = "created_at"
    readonly_fields = ["order_number", "created_at"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["commenter_name", "product", "sentiment", "is_public", "date_added"]
    search_fields = ["commenter_name", "body"]
    list_filter = ["sentiment", "is_public", "date_added"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient", "message", "order", "is_read", "created_at"]
    list_filter = ["is_read", "created_at"]
    search_fields = ["recipient__username", "message", "order__order_number"]
    list_select_related = ["recipient", "order"]
    date_hierarchy = "created_at"


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ["buyer", "product", "score", "order", "created_at"]
    list_filter = ["score", "created_at"]
    search_fields = ["buyer__username", "product__name", "order__order_number"]
    list_select_related = ["buyer", "product", "order"]
    date_hierarchy = "created_at"


@admin.register(CourierRating)
class CourierRatingAdmin(admin.ModelAdmin):
    list_display = ["buyer", "courier", "score", "order", "created_at"]
    list_filter = ["score", "created_at"]
    search_fields = ["buyer__username", "courier__user__username", "order__order_number"]
    list_select_related = ["buyer", "courier__user", "order"]
    date_hierarchy = "created_at"


admin.site.register(Country)
admin.site.register(City)


@admin.register(VirtualBankAccount)
class VirtualBankAccountAdmin(admin.ModelAdmin):
    list_display = ["account_number", "account_holder_name", "status", "forced_outcome", "balance_cents"]
    list_filter = ["status", "forced_outcome"]
    search_fields = ["account_number", "account_holder_name"]


@admin.register(SimulatedBankTransaction)
class SimulatedBankTransactionAdmin(admin.ModelAdmin):
    list_display = ["reference", "status", "amount_cents", "source_account", "attempt_count", "created_at"]
    list_filter = ["status"]
    search_fields = ["reference", "account_number_submitted"]
    list_select_related = ["source_account", "payment"]
    date_hierarchy = "created_at"


@admin.register(GatewayEventLog)
class GatewayEventLogAdmin(admin.ModelAdmin):
    list_display = ["transaction", "direction", "event_type", "status_code", "created_at"]
    list_filter = ["direction", "event_type"]
    search_fields = ["transaction__reference"]
    date_hierarchy = "created_at"
