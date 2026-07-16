from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("queue/", views.queue, name="queue"),
    path("queue/bulk/", views.queue_bulk, name="queue_bulk"),
    path("products/", views.products, name="products"),
    path("products/<slug:slug>/review/", views.product_review, name="product_review"),
    path("products/<slug:slug>/action/", views.product_action, name="product_action"),
    path("products/<slug:slug>/feature/", views.product_feature, name="product_feature"),
    path("products/<slug:slug>/remove/", views.product_remove, name="product_remove"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("users/<int:pk>/grant-role/", views.user_grant_role, name="user_grant_role"),
    path("users/<int:pk>/revoke-role/", views.user_revoke_role, name="user_revoke_role"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),
    path("comments/", views.comments, name="comments"),
    path("comments/<int:pk>/toggle/", views.comment_toggle, name="comment_toggle"),
    path("comments/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    path("payouts/", views.payouts, name="payouts"),
    path("payouts/run/", views.payouts_run, name="payouts_run"),
    path("payouts/<int:pk>/", views.payout_detail, name="payout_detail"),
    path("payouts/<int:pk>/action/", views.payout_action, name="payout_action"),
    path("subscriptions/", views.subscriptions, name="subscriptions"),
    path("subscriptions/<int:pk>/", views.subscription_detail, name="subscription_detail"),
    path("subscriptions/<int:pk>/action/", views.subscription_action, name="subscription_action"),
    path("audit/", views.audit, name="audit"),
    path("payment-settings/", views.platform_settings, name="platform_settings"),
    path("orders/", views.orders, name="orders"),
    path("orders/<int:order_id>/reassign-courier/", views.order_reassign_courier, name="order_reassign_courier"),
    path("couriers/", views.courier_verification, name="courier_verification"),
    path("couriers/<int:pk>/action/", views.courier_verification_action, name="courier_verification_action"),
    path("sellers/verification/", views.seller_verification, name="seller_verification"),
    path("sellers/verification/<int:pk>/action/", views.seller_verification_action, name="seller_verification_action"),
    path("restaurants/", views.restaurants, name="restaurants"),
]
