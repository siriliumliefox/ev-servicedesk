// Хранилище refresh-токена (ADR 0022 п. 7): только refresh, access живёт в памяти ApiClient.
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

abstract class TokenStore {
  Future<String?> read();
  Future<void> write(String refreshToken);
  Future<void> clear();

  /// Сохранённый вход потерян при обновлении хранилища — клиенту экран входа с сообщением, а не тихий сброс.
  /// Сообщается один раз.
  bool takeLostOnUpgrade();
}

/// Keychain (iOS/macOS) / Keystore (Android): без синхронизации в iCloud и переноса на другое устройство.
class SecureTokenStore implements TokenStore {
  SecureTokenStore._(this._storage, {required bool lostOnUpgrade}) : _lostOnUpgrade = lostOnUpgrade;

  static const _key = 'refresh_token';
  static const _installedKey = 'installed';

  final FlutterSecureStorage _storage;
  bool _lostOnUpgrade;

  /// Keychain переживает удаление приложения: при первом запуске после установки токен прошлой установки стирается.
  static Future<SecureTokenStore> open() async {
    // Android — собственные шифры flutter_secure_storage 11 (Keystore, AES-GCM); EncryptedSharedPreferences удалён.
    const storage = FlutterSecureStorage(
      iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
      mOptions: MacOsOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
    );
    final store = SecureTokenStore._(storage, lostOnUpgrade: await _lostOnUpgradeCheck(storage));
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

  @override
  bool takeLostOnUpgrade() {
    final lost = _lostOnUpgrade;
    _lostOnUpgrade = false;
    return lost;
  }

  /// Переход 9.x → 11.x напрямую (решение владельца 2026-10-18, PR #131): токен, сохранённый на Android
  /// в EncryptedSharedPreferences, версия 11 прочитать не может. Проверка только читает и идёт до первого
  /// read/write; iOS/macOS — всегда без потерь.
  static Future<bool> _lostOnUpgradeCheck(FlutterSecureStorage storage) async {
    try {
      final status = await storage.checkUpgradeStatus();
      if (status.hasDataLoss) debugPrint('token_store: вход потерян при обновлении хранилища: $status');
      return status.hasDataLoss;
    } on PlatformException catch (e) {
      debugPrint('token_store: checkUpgradeStatus недоступен: $e');
      return false;
    }
  }
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

  @override
  bool takeLostOnUpgrade() => false;
}
