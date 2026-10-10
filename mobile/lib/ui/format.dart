// Форматирование для интерфейса (ru): даты, пробег, телефон. Без пакета intl — до главы 18.

const _months = ['янв.', 'февр.', 'мар.', 'апр.', 'мая', 'июн.', 'июл.', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.'];

/// 2 окт. 2025
String formatDate(DateTime d) => '${d.day} ${_months[d.month - 1]} ${d.year}';

/// 8 окт., 18:40
String formatDateTime(DateTime d) =>
    '${d.day} ${_months[d.month - 1]}, ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';

/// 41 250 (неразрывные пробелы между разрядами).
String formatNumber(int n) {
  final s = n.abs().toString();
  final buf = StringBuffer(n < 0 ? '−' : '');
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) buf.write(' ');
    buf.write(s[i]);
  }
  return buf.toString();
}

String formatKm(int km) => '${formatNumber(km)} км';

/// 1 день, 2 дня, 5 дней.
String formatDays(int days) {
  final n = days.abs() % 100;
  final word = n % 10 == 1 && n != 11
      ? 'день'
      : (n % 10 >= 2 && n % 10 <= 4 && (n < 12 || n > 14))
          ? 'дня'
          : 'дней';
  return '${days.abs()} $word';
}

/// +375291234567 → +375 29 123-45-67.
String formatPhone(String e164) {
  final m = RegExp(r'^\+375(\d{2})(\d{3})(\d{2})(\d{2})$').firstMatch(e164);
  if (m == null) return e164;
  return '+375 ${m[1]} ${m[2]}-${m[3]}-${m[4]}';
}
