from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from . import views
from . import payment_views
from . import banking_api
from . import courier_api

app_name = "olretail"

# Independent courier app (Flutter, courier_app/) REST API — only the
# availability CRUD needs a full viewset/router, everything else is a
# single action per URL. See olretail/courier_api.py.
_courier_api_router = DefaultRouter()
_courier_api_router.register(
    "availability", courier_api.CourierAvailabilityViewSet, basename="courier-api-availability"
)

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

    # Wishlist
    path("wishlist/", payment_views.wishlist, name="wishlist"),
    path("wishlist/toggle/<int:product_id>/", payment_views.wishlist_toggle, name="wishlist_toggle"),
    path("wishlist/remove/<int:item_id>/", payment_views.wishlist_remove, name="wishlist_remove"),
    path("wishlist/move-to-cart/<int:item_id>/", payment_views.wishlist_move_to_cart, name="wishlist_move_to_cart"),

    # Checkout & Payment
    path("checkout/", payment_views.checkout, name="checkout"),
    path("payment/<int:order_id>/confirmation/", payment_views.payment_confirmation, name="payment_confirmation"),
    
    # Buyer Orders
    path("orders/", payment_views.buyer_orders, name="buyer_orders"),
    path("order/<int:order_id>/", payment_views.order_detail, name="order_detail"),
    path("order/<int:order_id>/cancel/", payment_views.cancel_order, name="cancel_order"),
    path("order/<int:order_id>/rate/", payment_views.rate_order, name="rate_order"),
    path("order/<int:order_id>/rate-courier/", payment_views.rate_courier, name="rate_courier"),

    # Bank transfer (buyer → platform)
    path("order/<int:order_id>/mark-sent/", payment_views.mark_payment_sent, name="mark_payment_sent"),

    # Delivery tracking
    path("order/<int:order_id>/delivery-update/", payment_views.add_delivery_update, name="add_delivery_update"),
    path("order/<int:order_id>/mark-delivered/", payment_views.mark_delivered, name="mark_delivered"),

    # Restaurant order workflow
    path("order/<int:order_id>/food-status/", payment_views.update_food_status, name="update_food_status"),
    path("order/<int:order_id>/courier-food-status/", payment_views.courier_update_food_status, name="courier_update_food_status"),

    # Courier
    path("courier/deliveries/", payment_views.courier_deliveries, name="courier_deliveries"),
    path("courier/verification/", payment_views.courier_submit_verification, name="courier_submit_verification"),
    path("courier/availability/", payment_views.courier_availability, name="courier_availability"),
    path("courier/availability/add/", payment_views.courier_availability_add, name="courier_availability_add"),
    path("courier/availability/<int:pk>/edit/", payment_views.courier_availability_edit, name="courier_availability_edit"),
    path("courier/availability/<int:pk>/delete/", payment_views.courier_availability_delete, name="courier_availability_delete"),

    # Disputes
    path("order/<int:order_id>/dispute/", payment_views.open_dispute, name="open_dispute"),
    path("dispute/<int:dispute_id>/", payment_views.dispute_detail, name="dispute_detail"),
    path("dispute/<int:dispute_id>/respond/", payment_views.seller_respond_dispute, name="seller_respond_dispute"),
    
    # Seller
    path("seller/", views.seller_dashboard, name="list"),
    path("seller/orders/", payment_views.seller_orders, name="seller_orders"),
    path("seller/balance/", payment_views.seller_balance, name="seller_balance"),
    path("seller/payment-settings/", payment_views.seller_payment_settings, name="seller_payment_settings"),
    path("seller/bank-accounts/add/", payment_views.seller_bank_account_add, name="seller_bank_account_add"),
    path("seller/bank-accounts/<int:pk>/delete/", payment_views.seller_bank_account_delete, name="seller_bank_account_delete"),
    path("seller/business-info/", payment_views.seller_business_identity, name="seller_business_identity"),
    path("seller/contact-info/", payment_views.seller_contact, name="seller_contact"),
    path("seller/location-info/", payment_views.seller_location, name="seller_location"),
    path("seller/branding/", payment_views.seller_branding, name="seller_branding"),
    path("seller/operations/", payment_views.seller_operations, name="seller_operations"),
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
    path("notifications/poll/", payment_views.notifications_poll, name="notifications_poll"),

    # Mobile app push notifications (Firebase Cloud Messaging — see /mobile)
    path("push/register-device/", payment_views.register_device_token, name="register_device_token"),
    path("push/unregister-device/", payment_views.unregister_device_token, name="unregister_device_token"),

    # Webhook
    path("webhook/stripe/", payment_views.stripe_webhook, name="stripe_webhook"),
    path("webhook/simulated-bank/", payment_views.simulated_bank_webhook, name="simulated_bank_webhook"),

    # Simulated Bank Gateway — developer REST API (see BANK_SIMULATOR_ARCHITECTURE.md)
    path("api/bank-simulator/v1/payments/", banking_api.create_payment, name="banking_api_create_payment"),
    path("api/bank-simulator/v1/payments/<str:reference>/", banking_api.get_payment, name="banking_api_get_payment"),
    path("api/bank-simulator/v1/payments/<str:reference>/cancel/", banking_api.cancel_payment, name="banking_api_cancel_payment"),
    path("api/bank-simulator/v1/payments/<str:reference>/refund/", banking_api.refund_payment, name="banking_api_refund_payment"),
    path("api/bank-simulator/v1/accounts/<str:account_number>/", banking_api.get_account, name="banking_api_get_account"),

    # Independent courier app (Flutter, courier_app/) REST API
    path("api/courier/v1/register/", courier_api.CourierRegisterView.as_view(), name="courier_api_register"),
    path("api/courier/v1/login/", courier_api.CourierLoginView.as_view(), name="courier_api_login"),
    path("api/courier/v1/logout/", courier_api.CourierLogoutView.as_view(), name="courier_api_logout"),
    path("api/courier/v1/me/", courier_api.MeView.as_view(), name="courier_api_me"),
    path("api/courier/v1/profile/", courier_api.CourierProfileView.as_view(), name="courier_api_profile"),
    path("api/courier/v1/earnings/", courier_api.EarningsView.as_view(), name="courier_api_earnings"),
    path("api/courier/v1/deliveries/", courier_api.DeliveriesListView.as_view(), name="courier_api_deliveries"),
    path(
        "api/courier/v1/deliveries/<int:order_id>/mark-delivered/",
        courier_api.MarkDeliveredView.as_view(), name="courier_api_mark_delivered",
    ),
    path("api/courier/v1/register-device/", courier_api.RegisterDeviceView.as_view(), name="courier_api_register_device"),
    path(
        "api/courier/v1/unregister-device/",
        courier_api.UnregisterDeviceView.as_view(), name="courier_api_unregister_device",
    ),
    path("api/courier/v1/", include(_courier_api_router.urls)),

    # Legacy routes kept so old bookmarks keep working
    path("login/", RedirectView.as_view(pattern_name="accounts:login", permanent=False), name="login"),
]
