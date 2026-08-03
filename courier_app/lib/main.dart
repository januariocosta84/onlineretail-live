import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import 'api_client.dart';
import 'push_notifications.dart';
import 'screens/deliveries_screen.dart';
import 'screens/login_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    // Fails gracefully (no google-services.json yet, misconfigured, no
    // network) — push notifications just stay unavailable rather than
    // crashing the app on startup. See push_notifications.dart.
    await Firebase.initializeApp();
    FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);
  } catch (_) {}
  runApp(const CourierApp());
}

class CourierApp extends StatelessWidget {
  const CourierApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TimorMart Courier',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1266F1)),
        useMaterial3: true,
      ),
      home: const _StartupGate(),
    );
  }
}

/// Decides whether to land on Login or Deliveries based on whether a token
/// is already stored (see AuthStorage) — the app never validates the token
/// against the server here; an expired/revoked token just fails on the
/// first real API call, which the deliveries screen already surfaces.
class _StartupGate extends StatefulWidget {
  const _StartupGate();

  @override
  State<_StartupGate> createState() => _StartupGateState();
}

class _StartupGateState extends State<_StartupGate> {
  final _api = ApiClient();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _api.isLoggedIn(),
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        // Secure storage failing to answer (or erroring) should never trap
        // the user on a spinner forever — fall back to Login, same as
        // "not logged in", and let them sign in again.
        return snapshot.data == true ? const DeliveriesScreen() : const LoginScreen();
      },
    );
  }
}
