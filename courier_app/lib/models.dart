// Data classes mirroring olretail/courier_api.py's serializers — kept as
// plain classes with hand-written fromJson, no code generation, to match
// this project's small v1 scope.

class DeliveryOrder {
  final int id;
  final String orderNumber;
  final String productName;
  final String buyerName;
  final String deliveryAddress;
  final String deliveryPhone;
  final String subtotal;
  final String status;
  final String? shippedAt;
  final String? deliveredAt;

  DeliveryOrder({
    required this.id,
    required this.orderNumber,
    required this.productName,
    required this.buyerName,
    required this.deliveryAddress,
    required this.deliveryPhone,
    required this.subtotal,
    required this.status,
    this.shippedAt,
    this.deliveredAt,
  });

  factory DeliveryOrder.fromJson(Map<String, dynamic> json) => DeliveryOrder(
        id: json['id'] as int,
        orderNumber: json['order_number'] as String,
        productName: json['product_name'] as String? ?? '',
        buyerName: json['buyer_name'] as String? ?? '',
        deliveryAddress: json['delivery_address'] as String? ?? '',
        deliveryPhone: json['delivery_phone'] as String? ?? '',
        subtotal: json['subtotal'] as String? ?? '0',
        status: json['status'] as String,
        shippedAt: json['shipped_at'] as String?,
        deliveredAt: json['delivered_at'] as String?,
      );
}

class AvailabilityWindow {
  final int id;
  final int weekday;
  final String startTime;
  final String endTime;

  static const weekdayNames = [
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
  ];

  AvailabilityWindow({
    required this.id,
    required this.weekday,
    required this.startTime,
    required this.endTime,
  });

  String get weekdayName => weekdayNames[weekday];

  factory AvailabilityWindow.fromJson(Map<String, dynamic> json) => AvailabilityWindow(
        id: json['id'] as int,
        weekday: json['weekday'] as int,
        // The API returns HH:MM:SS; trim to HH:MM for display/editing.
        startTime: (json['start_time'] as String).substring(0, 5),
        endTime: (json['end_time'] as String).substring(0, 5),
      );
}

class CourierMe {
  final String name;
  final String verificationStatus;

  CourierMe({required this.name, required this.verificationStatus});

  factory CourierMe.fromJson(Map<String, dynamic> json) => CourierMe(
        name: json['name'] as String,
        verificationStatus: json['verification_status'] as String,
      );
}

class CourierEarnings {
  final String month; // "YYYY-MM"
  final int deliveredCount;
  final int deliveredTotalCents;
  // Cash-on-delivery fees the courier already collected in person — not
  // part of outstandingCents, since the platform never held that money.
  final int codTotalCents;
  // Fees from non-COD deliveries — genuinely owed by the platform, this
  // is what feeds availableBalanceCents/outstandingCents.
  final int bankTotalCents;
  final int availableBalanceCents;
  final int pendingPayoutCents;
  final int outstandingCents;

  CourierEarnings({
    required this.month,
    required this.deliveredCount,
    required this.deliveredTotalCents,
    required this.codTotalCents,
    required this.bankTotalCents,
    required this.availableBalanceCents,
    required this.pendingPayoutCents,
    required this.outstandingCents,
  });

  double get deliveredTotalDollars => deliveredTotalCents / 100;
  double get codTotalDollars => codTotalCents / 100;
  double get bankTotalDollars => bankTotalCents / 100;
  double get availableBalanceDollars => availableBalanceCents / 100;
  double get pendingPayoutDollars => pendingPayoutCents / 100;
  double get outstandingDollars => outstandingCents / 100;

  factory CourierEarnings.fromJson(Map<String, dynamic> json) => CourierEarnings(
        month: json['month'] as String,
        deliveredCount: json['delivered_count'] as int,
        deliveredTotalCents: json['delivered_total_cents'] as int,
        codTotalCents: json['cod_total_cents'] as int,
        bankTotalCents: json['bank_total_cents'] as int,
        availableBalanceCents: json['available_balance_cents'] as int,
        pendingPayoutCents: json['pending_payout_cents'] as int,
        outstandingCents: json['outstanding_cents'] as int,
      );
}
