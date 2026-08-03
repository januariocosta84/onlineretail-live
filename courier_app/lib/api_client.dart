import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'auth_storage.dart';
import 'models.dart';

/// Thrown for any non-2xx response — [message] is the best human-readable
/// string we could pull out of the DRF error body (see [_errorMessage]).
class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => message;
}

/// Talks to olretail/courier_api.py. Base URL defaults to production and
/// can be overridden for local testing against `manage.py runserver`:
///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/courier/v1
/// (10.0.2.2 is the Android emulator's alias for the host machine's
/// localhost — a real device needs the host's LAN IP instead.)
class ApiClient {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://timormart.onrender.com/api/courier/v1',
  );

  final AuthStorage _authStorage;
  ApiClient({AuthStorage? authStorage}) : _authStorage = authStorage ?? AuthStorage();

  Uri _url(String path) => Uri.parse('$baseUrl$path');

  Future<Map<String, String>> _authHeaders() async {
    final token = await _authStorage.readToken();
    if (token == null) {
      throw ApiException(401, 'Not logged in.');
    }
    return {'Authorization': 'Token $token'};
  }

  String _errorMessage(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      if (body is Map) {
        if (body['detail'] != null) return body['detail'].toString();
        // DRF validation errors: {"field": ["message"]} or {"non_field_errors": [...]}
        final firstList = body.values.whereType<List>().firstOrNull;
        if (firstList != null && firstList.isNotEmpty) return firstList.first.toString();
        if (body['errors'] is Map) {
          final errors = body['errors'] as Map;
          final firstList2 = errors.values.whereType<List>().firstOrNull;
          if (firstList2 != null && firstList2.isNotEmpty) return firstList2.first.toString();
        }
      }
    } catch (_) {
      // fall through to the generic message below
    }
    return 'Request failed (${response.statusCode}).';
  }

  /// Logs in, stores the token, returns the courier's display name.
  Future<String> login(String username, String password) async {
    final response = await http.post(
      _url('/login/'),
      body: {'username': username, 'password': password},
    );
    if (response.statusCode != 200) {
      throw ApiException(response.statusCode, _errorMessage(response));
    }
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final token = body['token'] as String;
    final courierName = body['courier_name'] as String;
    await _authStorage.saveSession(token, courierName);
    return courierName;
  }

  Future<void> logout() => _authStorage.clear();

  Future<bool> isLoggedIn() async => (await _authStorage.readToken()) != null;

  Future<CourierMe> me() async {
    final response = await http.get(_url('/me/'), headers: await _authHeaders());
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
    return CourierMe.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// [month] defaults to the current month server-side when omitted.
  Future<CourierEarnings> earnings({DateTime? month}) async {
    final query = month == null
        ? ''
        : '?month=${month.year.toString().padLeft(4, '0')}-${month.month.toString().padLeft(2, '0')}';
    final response = await http.get(_url('/earnings/$query'), headers: await _authHeaders());
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
    return CourierEarnings.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  Future<({List<DeliveryOrder> pending, List<DeliveryOrder> delivered})> deliveries() async {
    final response = await http.get(_url('/deliveries/'), headers: await _authHeaders());
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    return (
      pending: (body['pending'] as List).map((e) => DeliveryOrder.fromJson(e)).toList(),
      delivered: (body['delivered'] as List).map((e) => DeliveryOrder.fromJson(e)).toList(),
    );
  }

  Future<void> markDelivered(int orderId, File photo) async {
    final headers = await _authHeaders();
    final request = http.MultipartRequest('POST', _url('/deliveries/$orderId/mark-delivered/'))
      ..headers.addAll(headers)
      ..files.add(await http.MultipartFile.fromPath('photo', photo.path));
    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
  }

  Future<List<AvailabilityWindow>> listAvailability() async {
    final response = await http.get(_url('/availability/'), headers: await _authHeaders());
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
    return (jsonDecode(response.body) as List).map((e) => AvailabilityWindow.fromJson(e)).toList();
  }

  Future<void> createAvailability({required int weekday, required String startTime, required String endTime}) async {
    final response = await http.post(
      _url('/availability/'),
      headers: await _authHeaders(),
      body: {'weekday': weekday.toString(), 'start_time': startTime, 'end_time': endTime},
    );
    if (response.statusCode != 201) throw ApiException(response.statusCode, _errorMessage(response));
  }

  Future<void> updateAvailability(int id,
      {required int weekday, required String startTime, required String endTime}) async {
    final response = await http.patch(
      _url('/availability/$id/'),
      headers: await _authHeaders(),
      body: {'weekday': weekday.toString(), 'start_time': startTime, 'end_time': endTime},
    );
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
  }

  Future<void> deleteAvailability(int id) async {
    final response = await http.delete(_url('/availability/$id/'), headers: await _authHeaders());
    if (response.statusCode != 204) throw ApiException(response.statusCode, _errorMessage(response));
  }

  /// Registers this device's FCM token so _notify()/send_push (see
  /// payment_views.py) can reach it — see lib/push_notifications.dart for
  /// where this gets called. Silently does nothing on failure (no token,
  /// logged out, offline): push is a nice-to-have, never something that
  /// should block using the app.
  Future<void> registerDeviceToken(String token, {String platform = 'android'}) async {
    final response = await http.post(
      _url('/register-device/'),
      headers: await _authHeaders(),
      body: {'token': token, 'platform': platform},
    );
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
  }

  /// Called on logout (see push_notifications.dart/deliveries_screen.dart)
  /// so a signed-out device stops receiving pushes meant for the account
  /// that just left it — without this, the token stays registered
  /// server-side indefinitely.
  Future<void> unregisterDeviceToken(String token) async {
    final response = await http.post(
      _url('/unregister-device/'),
      headers: await _authHeaders(),
      body: {'token': token},
    );
    if (response.statusCode != 200) throw ApiException(response.statusCode, _errorMessage(response));
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
