import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persists the DRF auth token (Keychain on iOS, EncryptedSharedPreferences
/// on Android) — see olretail/courier_api.py CourierLoginView, which is
/// what issues this token.
class AuthStorage {
  static const _tokenKey = 'courier_auth_token';
  static const _nameKey = 'courier_name';

  final _storage = const FlutterSecureStorage();

  Future<void> saveSession(String token, String courierName) async {
    await _storage.write(key: _tokenKey, value: token);
    await _storage.write(key: _nameKey, value: courierName);
  }

  Future<String?> readToken() => _storage.read(key: _tokenKey);

  Future<String?> readCourierName() => _storage.read(key: _nameKey);

  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _nameKey);
  }
}
