// Смена своего пароля в шапке кабинетов (общий компонент web-shared) (глава 25, ADR 0029 п. 14): проверка длины и повтора до запроса,
// ошибки сервера — у своих полей, успех — сообщение о завершении других сессий.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, ChangePasswordButton, WEAK_PASSWORD_TEXT } from "@ev-servicedesk/web-shared";

const NEW = "Mileage-Battery-Gomel";

async function open(onChange: (current: string, next: string) => Promise<void>) {
  const user = userEvent.setup();
  render(<ChangePasswordButton onChange={onChange} />);
  await user.click(screen.getByRole("button", { name: "Сменить пароль" }));
  return user;
}

async function fill(user: ReturnType<typeof userEvent.setup>, current: string, next: string, repeat = next) {
  await user.type(screen.getByLabelText("Текущий пароль"), current);
  await user.type(screen.getByLabelText("Новый пароль"), next);
  await user.type(screen.getByLabelText("Повторите новый пароль"), repeat);
  await user.click(screen.getAllByRole("button", { name: "Сменить пароль" }).at(-1)!);
}

describe("ChangePasswordButton", () => {
  it("короткий пароль и несовпадение повтора — без запроса", async () => {
    const onChange = vi.fn(async () => {});
    const user = await open(onChange);
    await fill(user, "current-pass", "short");
    expect(screen.getByText("Пароль — не короче 12 символов")).toBeTruthy();
    await user.clear(screen.getByLabelText("Новый пароль"));
    await user.type(screen.getByLabelText("Новый пароль"), NEW);
    await user.click(screen.getAllByRole("button", { name: "Сменить пароль" }).at(-1)!);
    expect(screen.getByText("Пароли не совпадают")).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("неверный текущий — у поля текущего, слабый новый — у поля нового", async () => {
    const onChange = vi
      .fn<(current: string, next: string) => Promise<void>>()
      .mockRejectedValueOnce(new ApiError("PASSWORD_INVALID", "Неверный текущий пароль.", 400))
      .mockRejectedValueOnce(new ApiError("VALIDATION_ERROR", WEAK_PASSWORD_TEXT, 422, "new_password"));
    const user = await open(onChange);
    await fill(user, "wrong-current", NEW);
    expect(screen.getByLabelText("Текущий пароль").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Неверный текущий пароль.")).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "Сменить пароль" }).at(-1)!);
    expect(screen.getByLabelText("Новый пароль").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(WEAK_PASSWORD_TEXT)).toBeTruthy();
  });

  it("успех — сообщение о завершении входа на других устройствах", async () => {
    const onChange = vi.fn(async () => {});
    const user = await open(onChange);
    await fill(user, "current-pass", NEW);
    expect(onChange).toHaveBeenCalledWith("current-pass", NEW);
    expect(screen.getByRole("status").textContent).toMatch(/других устройствах завершён/);
    await user.click(screen.getByRole("button", { name: "Готово" }));
    expect(screen.queryByText("Смена пароля")).toBeNull();
  });
});
