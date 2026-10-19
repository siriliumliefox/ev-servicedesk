// Текст уведомления о прошивке (#113, ADR 0033): его формирует сервер (createFirmwareRelease), а админ-панель
// показывает в предпросмотре — шаблон один, из описания операции в docs/openapi.yaml (проверяет тест).

export const FIRMWARE_CALL_TO_ACTION = "Запишитесь на обновление в сервисном центре.";

/** Тема и текст уведомления о прошивке — две строки, как у новости. `model` — «Марка Модель». */
export function firmwareMessage(version: string, model: string): string {
  return `Доступна прошивка ${version} для ${model}\n${FIRMWARE_CALL_TO_ACTION}`;
}
