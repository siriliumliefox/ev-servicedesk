/**
 * Базовые компоненты веба на токенах дизайн-системы (Глава 6, ADR 0010).
 * Те же компоненты и варианты — в библиотеке Figma «EV-ServiceDesk Design System».
 * Высоты: control-web (40) и control-web-sm (32); на мобильном — Flutter, control-mobile (48).
 */
import { useId, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-primary text-on-primary hover:bg-primary-hover",
  secondary: "bg-surface text-fg border border-border-strong hover:bg-surface-subtle",
  ghost: "bg-transparent text-fg hover:bg-surface-subtle",
  danger: "bg-danger text-on-danger hover:bg-danger-hover",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  md: "h-(--size-control-web) px-4",
  sm: "h-(--size-control-web-sm) px-3",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 rounded-md text-label transition-colors duration-(--duration-fast) disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-fg-disabled disabled:border-transparent ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]} ${className}`}
      {...props}
    />
  );
}

export function TextField({
  label,
  hint,
  error,
  className = "",
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const noteId = `${inputId}-note`;
  const note = error ?? hint;
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <label htmlFor={inputId} className="text-label text-fg">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={note ? noteId : undefined}
        className={`h-(--size-control-web) rounded-md border bg-surface px-3 text-body text-fg placeholder:text-fg-muted disabled:bg-surface-subtle disabled:text-fg-disabled ${error ? "border-danger-text" : "border-border-strong"}`}
        {...props}
      />
      {note && (
        <p id={noteId} className={`text-caption ${error ? "text-danger-text" : "text-fg-muted"}`}>
          {note}
        </p>
      )}
    </div>
  );
}

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-lg border border-border bg-surface p-4 shadow-sm ${className}`} {...props} />;
}
