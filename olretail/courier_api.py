"""REST API for the independent courier app (courier_app/, Flutter).

Token-authenticated (see REST_FRAMEWORK in settings and the login view
below) — a native app can't carry Django's session cookie/CSRF token the
way the webview-based mobile/ app does. Every view here is courier-only
(IsCourier) and deliberately narrow: v1 is the core delivery loop (list
assigned deliveries, mark one delivered, manage the weekly availability
schedule) — see HANDOFF.md for what's intentionally out of scope.

Business logic is NOT duplicated here: mark-delivered reuses
DeliveryProofForm and _apply_order_delivered from payment_views.py, the
exact same code path the HTML view uses, so money-flow/notification
behavior can't drift between the website and this API.
"""

from rest_framework import serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import CourierAvailability
from .payment_forms import DeliveryProofForm
from .payment_models import CourierBalance, DevicePlatform, DeviceToken, Order, OrderStatus, PaymentMethod
from .payment_views import _apply_order_delivered, _courier_can_mark_delivered


class IsCourier(BasePermission):
    """Only a logged-in user with a Courier profile — see accounts.roles
    and olretail.decorators.courier_required, the same rule this API
    mirrors for the web views."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and hasattr(request.user, 'courier'))


class CourierLoginView(ObtainAuthToken):
    """POST {username, password} -> {token, courier_name}. Rejects any
    account without a Courier profile — a buyer/seller/admin credential is
    valid for Django auth but not for this app."""

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        if not hasattr(user, 'courier'):
            return Response({'detail': 'This account is not a courier account.'}, status=status.HTTP_403_FORBIDDEN)
        token, _created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key, 'courier_name': user.courier.get_name})


class MeView(APIView):
    """Read-only courier identity for the app's home/header — verification
    status is shown but not submittable here (see HANDOFF.md v1 scope)."""

    permission_classes = [IsCourier]

    def get(self, request):
        courier = request.user.courier
        return Response({
            'name': courier.get_name,
            'verification_status': courier.verification_status,
        })


class EarningsView(APIView):
    """GET ?month=YYYY-MM (defaults to the current month) -> this month's
    delivered-order fee totals, split by how the order was paid, plus the
    running CourierBalance figures: available (earned, not yet scheduled)
    and pending (scheduled/processing) — both surfaced so the app can
    explain *why* something is outstanding, alongside a combined
    outstanding_cents headline figure.

    The COD/bank split matters because they're accounted for completely
    differently — see _apply_order_delivered (payment_views.py): a cash-
    on-delivery fee is money the courier already collected directly from
    the buyer (cod_total_cents is informational only, it was never added
    to CourierBalance), while a non-COD fee is money the platform still
    owes and will eventually pay out (bank_total_cents feeds directly into
    outstanding_cents via CourierBalance). See CourierBalance/CourierPayout
    (payment_models.py) and create_scheduled_courier_payouts (payouts.py)
    for what happens next."""

    permission_classes = [IsCourier]

    def get(self, request):
        courier = request.user.courier
        month_param = request.query_params.get('month')
        if month_param:
            try:
                year_str, month_str = month_param.split('-')
                year, month = int(year_str), int(month_str)
                if not 1 <= month <= 12:
                    raise ValueError
            except ValueError:
                return Response({'detail': 'month must be in YYYY-MM format.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            today = timezone.localdate()
            year, month = today.year, today.month

        delivered = Order.objects.filter(
            assigned_courier=courier, status=OrderStatus.DELIVERED,
            delivered_at__year=year, delivered_at__month=month,
        )
        cod_total = delivered.filter(payment_method=PaymentMethod.CASH_ON_DELIVERY).aggregate(
            total=Sum('courier_fee_cents')
        )['total'] or 0
        bank_total = delivered.exclude(payment_method=PaymentMethod.CASH_ON_DELIVERY).aggregate(
            total=Sum('courier_fee_cents')
        )['total'] or 0
        balance, _created = CourierBalance.objects.get_or_create(courier=courier)
        return Response({
            'month': f'{year:04d}-{month:02d}',
            'delivered_count': delivered.count(),
            'delivered_total_cents': cod_total + bank_total,
            'cod_total_cents': cod_total,
            'bank_total_cents': bank_total,
            'available_balance_cents': balance.available_balance,
            'pending_payout_cents': balance.pending_payout,
            'outstanding_cents': balance.available_balance + balance.pending_payout,
        })


class OrderSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    buyer_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'product_name', 'buyer_name', 'delivery_address', 'delivery_phone',
            'delivery_latitude', 'delivery_longitude',
            'subtotal', 'payment_method', 'status', 'shipped_at', 'delivered_at', 'food_status',
        ]

    def get_buyer_name(self, obj):
        return obj.buyer.get_full_name() or obj.buyer.username


class DeliveriesListView(APIView):
    """Same two buckets as olretail.payment_views.courier_deliveries
    (the web page) — pending (shipped, awaiting delivery) and the last 20
    delivered."""

    permission_classes = [IsCourier]

    def get(self, request):
        courier = request.user.courier
        orders = Order.objects.filter(assigned_courier=courier).select_related('product', 'buyer', 'seller')
        pending = orders.filter(status=OrderStatus.SHIPPED).order_by('-shipped_at')
        delivered = orders.filter(status=OrderStatus.DELIVERED).order_by('-delivered_at')[:20]
        return Response({
            'pending': OrderSerializer(pending, many=True).data,
            'delivered': OrderSerializer(delivered, many=True).data,
        })


class MarkDeliveredView(APIView):
    """POST multipart {photo} -> marks the order delivered via the shared
    _apply_order_delivered helper (payment_views.py) — settles COD if
    needed, credits the seller's payout balance, notifies the buyer and
    any Finance Officers, exactly like the web "Mark Delivered" button."""

    permission_classes = [IsCourier]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)
        _is_owning_seller, is_assigned_courier = _courier_can_mark_delivered(request.user, order)
        if not is_assigned_courier:
            return Response({'detail': 'This order is not assigned to you.'}, status=status.HTTP_403_FORBIDDEN)
        if order.status != OrderStatus.SHIPPED:
            return Response(
                {'detail': 'Only shipped orders can be marked as delivered.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        form = DeliveryProofForm(request.POST, request.FILES)
        if not form.is_valid():
            return Response({'errors': form.errors}, status=status.HTTP_400_BAD_REQUEST)
        _apply_order_delivered(order, form.cleaned_data['photo'])
        return Response({'status': 'delivered'})


class RegisterDeviceView(APIView):
    """POST {token, platform} -> registers this device for push
    notifications (courier assigned, etc. — see _notify()/send_push in
    payment_views.py and push_notifications.py). Mirrors
    payment_views.register_device_token, which is session-authenticated
    and unreachable from this token-authenticated native app. Re-posting
    an existing token just reassigns it — tokens are unique per install,
    not per user, same as the web/Capacitor version."""

    permission_classes = [IsCourier]

    def post(self, request):
        token = (request.data.get('token') or '').strip()
        platform = request.data.get('platform') or ''
        if not token or platform not in DevicePlatform.values:
            return Response(
                {'detail': 'token and a valid platform are required.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        DeviceToken.objects.update_or_create(token=token, defaults={'user': request.user, 'platform': platform})
        return Response({'status': 'ok'})


class UnregisterDeviceView(APIView):
    """POST {token} -> called on logout so a signed-out device stops
    receiving pushes meant for the account that just left it. Mirrors
    payment_views.unregister_device_token (session-authenticated, same as
    RegisterDeviceView's web counterpart). Without this, a courier who
    logs out keeps every future push for whoever's account they were
    signed into — see lib/screens/deliveries_screen.dart's logout."""

    permission_classes = [IsCourier]

    def post(self, request):
        token = (request.data.get('token') or '').strip()
        if token:
            DeviceToken.objects.filter(token=token, user=request.user).delete()
        return Response({'status': 'ok'})


class CourierAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierAvailability
        fields = ['id', 'weekday', 'start_time', 'end_time']

    def validate(self, attrs):
        start = attrs.get('start_time', getattr(self.instance, 'start_time', None))
        end = attrs.get('end_time', getattr(self.instance, 'end_time', None))
        if start and end and end <= start:
            raise serializers.ValidationError('End time must be after start time.')
        return attrs


class CourierAvailabilityViewSet(viewsets.ModelViewSet):
    """CRUD over the current courier's own weekly schedule — same model
    and validation as CourierAvailabilityForm (payment_forms.py), used by
    the web My Availability page."""

    serializer_class = CourierAvailabilitySerializer
    permission_classes = [IsCourier]

    def get_queryset(self):
        return self.request.user.courier.availability_windows.all()

    def perform_create(self, serializer):
        serializer.save(courier=self.request.user.courier)
