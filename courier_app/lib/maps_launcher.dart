import 'package:url_launcher/url_launcher.dart';

/// Opens the device's own Maps app with driving directions from the
/// courier's current location to a delivery pin — deliberately not an
/// embedded map/routing widget: no SDK or API key needed, and every
/// courier already has a maps app that does real turn-by-turn navigation
/// better than anything worth building here. Google Maps' web deep link
/// (maps.google.com) opens the native app on both Android and iOS when
/// installed, falling back to the browser otherwise.
class MapsLauncherException implements Exception {
  final String message;
  MapsLauncherException(this.message);
  @override
  String toString() => message;
}

Future<void> launchRouteTo(double lat, double lng) async {
  final uri = Uri.parse(
    'https://www.google.com/maps/dir/?api=1&destination=$lat,$lng&travelmode=driving',
  );
  final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
  if (!opened) {
    throw MapsLauncherException('Could not open a maps app.');
  }
}
