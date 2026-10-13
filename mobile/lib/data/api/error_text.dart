// Тексты ошибок API для пользователя (ADR 0022 п. 12): Error.message сервера — для логов, не для UI.

/// Текст для кода ошибки контракта; details и Retry-After уточняют текст, неизвестный код — общий текст.
String errorText(String code, {Map<String, Object?>? details, int? retryAfterSeconds}) {
  switch (code) {
    case 'CODE_INVALID':
      final left = details?['attempts_left'];
      return left is int && left > 0 ? 'Неверный код. Осталось попыток: $left' : 'Неверный код. Запросите новый';
    case 'CODE_EXPIRED':
      return 'Код устарел. Запросите новый';
    case 'RATE_LIMITED':
      return retryAfterSeconds == null
          ? 'Слишком много попыток. Повторите позже'
          : 'Слишком много попыток. Повторите через ${_wait(retryAfterSeconds)}';
    case 'PHONE_NOT_SUPPORTED':
      return 'На этот номер SMS не доставляются. Укажите другой номер';
    case 'SMS_UNAVAILABLE':
      return 'Не удалось отправить SMS. Повторите через минуту';
    case 'STAFF_PASSWORD_LOGIN':
      return 'Этот номер принадлежит сотруднику — войдите в кабинет сотрудника';
    case 'ACCOUNT_DISABLED':
      return 'Вход заблокирован. Обратитесь в сервисный центр';
    case 'PD_CONSENT_REQUIRED':
      return 'Чтобы продолжить, примите согласие на обработку персональных данных';
    case 'PD_CONSENT_NOT_ACTIVE':
      return 'Согласие на обработку персональных данных уже отозвано';
    case 'VIN_DECODE_FAILED':
      return 'Не удалось определить модель по VIN — выберите её из списка';
    case 'VIN_REGISTERED_TO_ANOTHER_ACCOUNT':
      return 'Этот VIN уже привязан к другому аккаунту. Обратитесь в сервисный центр';
    case 'VIN_ALREADY_ADDED':
      return 'Этот автомобиль уже есть в вашем списке';
    case 'VEHICLE_MODEL_NOT_FOUND':
      return 'Модель не найдена — выберите её из списка';
    case 'MILEAGE_DECREASE':
      return 'Пробег не может быть меньше текущего. Если ошиблись при вводе — обратитесь в сервисный центр';
    case 'TICKET_RESOLVED':
      return 'Обращение уже решено — создайте новое';
    case 'ATTACHMENT_TYPE_NOT_ALLOWED':
      return 'Этот формат файла не подходит. Прикрепите фото (JPEG, PNG, HEIC) или видео (MP4, MOV)';
    case 'ATTACHMENT_TOO_LARGE':
      return 'Файл слишком большой: фото — до 20 МБ, видео — до 200 МБ';
    case 'TOO_MANY_ATTACHMENTS':
      return 'Можно прикрепить не больше 10 файлов';
    case 'ATTACHMENT_NOT_FOUND':
    case 'ATTACHMENT_ALREADY_USED':
    case 'UPLOAD_FAILED':
      return 'Не удалось загрузить файл. Прикрепите его ещё раз';
    case 'NOT_FOUND':
      return 'Данные не найдены — возможно, они были удалены';
    case 'VALIDATION_ERROR':
      return 'Проверьте введённые данные';
    case 'UNAUTHORIZED':
    case 'TOKEN_REVOKED':
      return sessionEndedText;
    default:
      return 'Что-то пошло не так. Повторите позже';
  }
}

const sessionEndedText = 'Сессия завершена — войдите снова';

String _wait(int seconds) {
  if (seconds < 60) return '$seconds с';
  final minutes = (seconds / 60).ceil();
  if (minutes < 60) return '$minutes мин';
  return '${(minutes / 60).ceil()} ч';
}
