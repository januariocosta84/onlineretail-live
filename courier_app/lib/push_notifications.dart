import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'api_client.dart';

/// Must match olretail/push_notifications.py's ANDROID_CHANNEL_ID — the
/// backend already targets every push at this channel id; this is what
/// actually routes it there instead of Android's silent default channel.
const _channelId = 'default';

final _localNotifications = FlutterLocalNotificationsPlugin();

/// FCM requires a top-level (or static) function for background message
/// handling, run in a separate isolate. There's nothing to do inside it:
/// every push this app receives carries a "notification" payload (see
/// push_notifications.py's send_push), which the OS displays
/// automatically while the app is backgrounded/terminated — as long as
/// the manifest's default_notification_channel_id meta-data points at a
/// real, HIGH-importance channel (created below). This handler only needs
/// to exist so FCM's background isolate wiring is registered at all.
@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {}

/// Best-effort push notification setup — every step here (permission,
/// token fetch, registering it with the backend) can fail (denied,
/// offline, Firebase not configured yet because google-services.json
/// hasn't been dropped in) without ever blocking the rest of the app.
class PushNotifications {
  static bool _initialized = false;

  /// Call once a courier is logged in (see login_screen.dart and
  /// deliveries_screen.dart's startup path) — Firebase.initializeApp()
  /// must already have run (see main.dart).
  static Future<void> init(ApiClient api) async {
    if (_initialized) return;
    _initialized = true;

    try {
      await _createAndroidChannel();

      final messaging = FirebaseMessaging.instance;
      await messaging.requestPermission(alert: true, badge: true, sound: true);

      final token = await messaging.getToken();
      if (token != null) await api.registerDeviceToken(token);
      // FCM rotates tokens occasionally (reinstall, app data cleared,
      // periodic refresh) — an unregistered new token means silence.
      messaging.onTokenRefresh.listen((newToken) {
        api.registerDeviceToken(newToken).catchError((_) {});
      });

      // Foreground messages don't auto-display anything (that's an FCM/OS
      // behavior, not something this app controls) — show one ourselves
      // via flutter_local_notifications, on the same channel, so a
      // courier with the app open still gets the sound/vibration alert.
      FirebaseMessaging.onMessage.listen(_showForegroundNotification);
    } catch (_) {
      // See class docstring — push is a nice-to-have, not a dependency.
    }
  }

  static Future<void> _createAndroidChannel() async {
    const channel = AndroidNotificationChannel(
      _channelId,
      'TimorMart Courier',
      description: 'Delivery assignments and order updates.',
      importance: Importance.high,
      playSound: true,
      enableVibration: true,
    );
    await _localNotifications.initialize(
      const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')),
    );
    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);
  }

  static void _showForegroundNotification(RemoteMessage message) {
    final notification = message.notification;
    if (notification == null) return;
    _localNotifications.show(
      notification.hashCode,
      notification.title,
      notification.body,
      const NotificationDetails(
        android: AndroidNotificationDetails(
          _channelId,
          'TimorMart Courier',
          channelDescription: 'Delivery assignments and order updates.',
          importance: Importance.high,
          priority: Priority.high,
          playSound: true,
          enableVibration: true,
        ),
      ),
    );
  }
}
