// Хранилище refresh-токена (ADR 0022 п. 7): только refresh, access живёт в памяти ApiClient.
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

abstract class TokenStore {
  Future<String?> read();
  Future<void> write(String refreshToken);
  Future<void> clear();
}

/// Keychain (iOS/macOS) / Keystore (Android): без синхронизации в iCloud и переноса на другое устройство.
class SecureTokenStore implements TokenStore {
  SecureTokenStore._(this._storage);

  static const _key = 'refresh_token';
  static const _installedKey = 'installed';

  final FlutterSecureStorage _storage;

  /// Keychain переживает удаление приложения: при первом запуске после установки токен прошлой установки стирается.
  static Future<SecureTokenStore> open() async {
    const storage = FlutterSecureStorage(
      iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
      mOptions: MacOsOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
      aOptions: AndroidOptions(encryptedSharedPreferences: true),
    );
    final store = SecureTokenStore._(storage);
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_installedKey) != true) {
      await store.clear();
      await prefs.setBool(_installedKey, true);
    }
    return store;
  }

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String refreshToken) => _storage.write(key: _key, value: refreshToken);

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

/// Для тестов и E2E на уровне API.
class MemoryTokenStore implements TokenStore {
  MemoryTokenStore([this.token]);

  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String refreshToken) async => token = refreshToken;

  @override
  Future<void> clear() async => token = null;
}
