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
  final String paymentMethod;
  final String status;
  final String? shippedAt;
  final String? deliveredAt;
  // Buyer-shared GPS pin from checkout (see olretail/courier_api.py
  // OrderSerializer) — null when the buyer picked a city manually instead
  // of sharing a location.
  final double? deliveryLatitude;
  final double? deliveryLongitude;

  DeliveryOrder({
    required this.id,
    required this.orderNumber,
    required this.productName,
    required this.buyerName,
    required this.deliveryAddress,
    required this.deliveryPhone,
    required this.subtotal,
    required this.paymentMethod,
    required this.status,
    this.shippedAt,
    this.deliveredAt,
    this.deliveryLatitude,
    this.deliveryLongitude,
  });

  bool get hasPin => deliveryLatitude != null && deliveryLongitude != null;
  // Cash on delivery is the only method where the courier actually
  // collects money — every electronic method (card, bank transfer) is
  // already settled with the platform, so the amount is none of the
  // courier's business to see.
  bool get isCashOnDelivery => paymentMethod == 'cash_on_delivery';

  factory DeliveryOrder.fromJson(Map<String, dynamic> json) => DeliveryOrder(
        id: json['id'] as int,
        orderNumber: json['order_number'] as String,
        productName: json['product_name'] as String? ?? '',
        buyerName: json['buyer_name'] as String? ?? '',
        deliveryAddress: json['delivery_address'] as String? ?? '',
        deliveryPhone: json['delivery_phone'] as String? ?? '',
        subtotal: json['subtotal'] as String? ?? '0',
        paymentMethod: json['payment_method'] as String? ?? '',
        status: json['status'] as String,
        shippedAt: json['shipped_at'] as String?,
        deliveredAt: json['delivered_at'] as String?,
        // DRF serializes DecimalField as a string, not a JSON number.
        deliveryLatitude: json['delivery_latitude'] != null
            ? double.tryParse(json['delivery_latitude'] as String)
            : null,
        deliveryLongitude: json['delivery_longitude'] != null
            ? double.tryParse(json['delivery_longitude'] as String)
            : null,
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

/// Mirrors olretail/courier_api.py's CourierProfileSerializer — used by
/// the profile screen (view + edit mobile/address/documents).
class CourierProfile {
  final String firstName;
  final String lastName;
  final String email;
  final String mobile;
  final String address;
  final String verificationStatus;
  final String verificationNote;
  final bool hasIdDocument;
  final bool hasDrivingLicense;

  CourierProfile({
    required this.firstName,
    required this.lastName,
    required this.email,
    required this.mobile,
    required this.address,
    required this.verificationStatus,
    required this.verificationNote,
    required this.hasIdDocument,
    required this.hasDrivingLicense,
  });

  String get fullName => '$firstName $lastName'.trim();

  factory CourierProfile.fromJson(Map<String, dynamic> json) => CourierProfile(
        firstName: json['first_name'] as String? ?? '',
        lastName: json['last_name'] as String? ?? '',
        email: json['email'] as String? ?? '',
        mobile: json['mobile'] as String? ?? '',
        address: json['address'] as String? ?? '',
        verificationStatus: json['verification_status'] as String? ?? '',
        verificationNote: json['verification_note'] as String? ?? '',
        hasIdDocument: json['has_id_document'] as bool? ?? false,
        hasDrivingLicense: json['has_driving_license'] as bool? ?? false,
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
