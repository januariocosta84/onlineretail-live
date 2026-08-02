// Smoke test for the login screen. Pumps LoginScreen directly rather than
// the full CourierApp/_StartupGate — _StartupGate's isLoggedIn() check goes
// through flutter_secure_storage's platform channel, which has no handler
// registered in a plain `flutter test` run and hangs pumpAndSettle. That's
// a test-environment limitation, not an app bug (real devices always have
// the channel); real end-to-end verification for this app is the Django
// API test-client coverage plus `flutter build apk`, not widget tests.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:courier_app/screens/login_screen.dart';

void main() {
  testWidgets('Login screen shows the username/password form', (WidgetTester tester) async {
    await tester.pumpWidget(const MaterialApp(home: LoginScreen()));
    await tester.pumpAndSettle();

    expect(find.text('TimorMart Courier'), findsOneWidget);
    expect(find.widgetWithText(TextFormField, 'Username'), findsOneWidget);
    expect(find.widgetWithText(TextFormField, 'Password'), findsOneWidget);
  });
}
