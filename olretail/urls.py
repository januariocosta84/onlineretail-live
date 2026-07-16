from django.urls import path
from django.views.generic import RedirectView

from . import views
from . import payment_views

app_name = "olretail"

urlpatterns = [
    path("", views.index, name="index"),
    path("about/", views.about, name="about"),
    path("search/", views.search, name="search"),
    path("details/<slug:slug>/", views.product_detail, name="details"),
    path("category/<int:id>", views.category_redirect, name="category"),
    
    # Cart
    path("cart/", payment_views.cart, name="cart"),
    path("cart/add/<int:product_id>/", payment_views.add_to_cart, name="add_to_cart"),
    path("cart/update/<int:cart_id>/", payment_views.update_cart, name="update_cart"),
    path("cart/remove/<int:cart_id>/", payment_views.remove_from_cart, name="remove_from_cart"),
    path("cart/clear/", payment_views.clear_cart, name="clear_cart"),
    
    # Checkout & Payment
    path("checkout/", payment_views.checkout, name="checkout"),
    path("payment/<int:order_id>/confirmation/", payment_views.payment_confirmation, name="payment_confirmation"),
    
    # Buyer Orders
    path("orders/", payment_views.buyer_orders, name="buyer_orders"),
    path("order/<int:order_id>/", payment_views.order_detail, name="order_detail"),
    path("order/<int:order_id>/cancel/", payment_views.cancel_order, name="cancel_order"),
    path("order/<int:order_id>/rate/", payment_views.rate_order, name="rate_order"),
    path("order/<int:order_id>/rate-courier/", payment_views.rate_courier, name="rate_courier"),

    # Bank / mobile transfer
    path("order/<int:order_id>/mark-sent/", payment_views.mark_payment_sent, name="mark_payment_sent"),
    path("order/<int:order_id>/confirm-received/", payment_views.confirm_payment_received, name="confirm_payment_received"),

    # Delivery tracking
    path("order/<int:order_id>/delivery-update/", payment_views.add_delivery_update, name="add_delivery_update"),
    path("order/<int:order_id>/mark-delivered/", payment_views.mark_delivered, name="mark_delivered"),

    # Restaurant order workflow
    path("order/<int:order_id>/food-status/", payment_views.update_food_status, name="update_food_status"),
    path("order/<int:order_id>/courier-food-status/", payment_views.courier_update_food_status, name="courier_update_food_status"),

    # Courier
    path("courier/deliveries/", payment_views.courier_deliveries, name="courier_deliveries"),
    path("courier/verification/", payment_views.courier_submit_verification, name="courier_submit_verification"),

    # Disputes
    path("order/<int:order_id>/dispute/", payment_views.open_dispute, name="open_dispute"),
    path("dispute/<int:dispute_id>/", payment_views.dispute_detail, name="dispute_detail"),
    path("dispute/<int:dispute_id>/respond/", payment_views.seller_respond_dispute, name="seller_respond_dispute"),
    
    # Seller
    path("seller/", views.seller_dashboard, name="list"),
    path("seller/orders/", payment_views.seller_orders, name="seller_orders"),
    path("seller/balance/", payment_views.seller_balance, name="seller_balance"),
    path("seller/payment-settings/", payment_views.seller_payment_settings, name="seller_payment_settings"),
    path("seller/company-info/", payment_views.seller_company_info, name="seller_company_info"),
    path("seller/verification/", payment_views.seller_submit_verification, name="seller_submit_verification"),
    path("seller/subscription/", payment_views.seller_subscription, name="seller_subscription"),
    path("seller/order/<int:order_id>/status/", payment_views.seller_update_order_status, name="seller_update_order_status"),
    path("seller/create-product/", views.product_create, name="create_product"),
    path("seller/update-product/<slug:slug>", views.product_update, name="update_product"),
    path("seller/mark-sold/<slug:slug>", views.product_mark_sold, name="mark_sold"),
    path("seller/delete-product/<slug:slug>", views.product_delete, name="delete_product"),
    path("seller/menu-categories/", views.menu_categories, name="menu_categories"),
    path("seller/menu-categories/<int:pk>/delete/", views.menu_category_delete, name="menu_category_delete"),
    
    # Notifications
    path("notifications/", payment_views.notifications, name="notifications"),
    path("notifications/<int:pk>/open/", payment_views.notification_open, name="notification_open"),
    path("notifications/mark-all-read/", payment_views.notifications_mark_all_read, name="notifications_mark_all_read"),

    # Webhook
    path("webhook/stripe/", payment_views.stripe_webhook, name="stripe_webhook"),
    
    # Legacy routes kept so old bookmarks keep working
    path("login/", RedirectView.as_view(pattern_name="accounts:login", permanent=False), name="login"),
]
