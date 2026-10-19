import 'dart:math';

/// Ключ повтора отправки — `client_request_id` (ADR 0031, #111).
///
/// Ответ на отправку мог не дойти (тайм-аут, обрыв связи), а сервер — уже записать обращение или
/// сообщение. Повтор того же черновика идёт с тем же ключом, и сервер отвечает записанным, а не
/// создаёт дубль. Изменённый черновик — новый ключ; после успешной отправки — [reset].
class RetryKey {
  RetryKey({Random? random}) : _random = random ?? Random.secure();

  final Random _random;
  String? _draft;
  String? _key;

  /// Ключ для черновика: [draft] — всё содержимое отправки одной строкой.
  String forDraft(String draft) {
    if (_key == null || draft != _draft) {
      _draft = draft;
      _key = newRequestId(_random);
    }
    return _key!;
  }

  /// Черновик отправлен — следующая отправка получит новый ключ.
  void reset() {
    _draft = null;
    _key = null;
  }
}

/// UUID версии 4 (RFC 9562) из криптостойкого генератора.
String newRequestId([Random? random]) {
  final r = random ?? Random.secure();
  final bytes = List<int>.generate(16, (_) => r.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // версия 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // вариант RFC 9562
  final hex = [for (final b in bytes) b.toRadixString(16).padLeft(2, '0')].join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}
