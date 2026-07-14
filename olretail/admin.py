from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import Buyer, Category, City, Comment, Country, Courier, Order, Product, ProductStatus, Seller

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
    list_display = ["get_name", "mobile", "address"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "mobile"]


@admin.register(Buyer)
class BuyerAdmin(admin.ModelAdmin):
    list_display = ["get_name", "mobile", "address"]


@admin.register(Courier)
class CourierAdmin(admin.ModelAdmin):
    list_display = ["get_name", "mobile"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "mobile"]


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


admin.site.register(Country)
admin.site.register(City)
