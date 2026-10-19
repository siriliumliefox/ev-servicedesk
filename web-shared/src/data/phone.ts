// Номер телефона сотрудника из ввода в любом виде (#114): поле начинается с «+375», а номер часто вставляют
// целиком — «+375 29 111-22-33», «375291112233», «8 029 111-22-33». Правила — как в мобильном клиенте
// (`belarusSubscriberDigits`): коды операторов и городов Беларуси не начинаются с 375 и 80, поэтому в номере
// длиннее 9 цифр это код страны или выход на междугороднюю связь, а не начало номера.

/** E.164 для белорусского номера (+375 и 9 цифр абонента); иной номер — «+» и его цифры (проверит сервер). */
export function normalizePhone(input: string): string {
  const all = input.replace(/\D/g, "");
  let digits = all;
  while (digits.length > 9 && digits.startsWith("375")) digits = digits.slice(3);
  if (digits.length > 9 && digits.startsWith("80")) digits = digits.slice(2);
  if (digits.length === 9) return `+375${digits}`;
  // Не белорусский номер: префикс поля «+375» перед вставленным «+7…» — не часть номера.
  const pasted = input.replace(/^\s*\+375\s*(?=\+)/, "");
  return `+${pasted.replace(/\D/g, "") || all}`;
}
