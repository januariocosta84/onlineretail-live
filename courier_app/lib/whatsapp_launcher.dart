import 'package:url_launcher/url_launcher.dart';

/// Opens a WhatsApp chat with a buyer's delivery phone number — couriers
/// coordinate pickup/drop-off details over WhatsApp far more often than an
/// actual phone call in this market, so this is the more useful tap target
/// than tel:. wa.me needs the number in international format with no
/// leading '+', spaces, or dashes; Timor-Leste numbers are collected at
/// checkout as either a bare local number ("7712345") or with the country
/// code already present ("+670 7712345") — see CheckoutForm's placeholder
/// text in olretail/payment_forms.py — so a bare number gets '670'
/// prepended here.
class WhatsAppLauncherException implements Exception {
  final String message;
  WhatsAppLauncherException(this.message);
  @override
  String toString() => message;
}

String _toInternational(String phone) {
  var digits = phone.replaceAll(RegExp(r'[^0-9]'), '');
  if (digits.startsWith('0')) digits = digits.substring(1);
  if (!digits.startsWith('670')) digits = '670$digits';
  return digits;
}

Future<void> launchWhatsApp(String phone) async {
  final uri = Uri.parse('https://wa.me/${_toInternational(phone)}');
  final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
  if (!opened) {
    throw WhatsAppLauncherException('Could not open WhatsApp.');
  }
}
