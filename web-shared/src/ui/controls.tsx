/**
 * Поля и переключатели веба на токенах (Глава 8, дополняют компоненты главы 6 в `components.tsx`).
 * Высота полей — control-web (40), чипов — control-web-sm (32).
 */
import { useId, type ButtonHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const FIELD =
  "rounded-md border bg-surface px-3 text-body text-fg placeholder:text-fg-muted disabled:bg-surface-subtle disabled:text-fg-disabled";

function FieldShell({
  label,
  hint,
  error,
  id,
  inline = false,
  className = "",
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  id: string;
  /** Подпись слева от поля — для строки фильтров. */
  inline?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const note = error ?? hint;
  return (
    <div className={`flex ${inline ? "flex-row items-center gap-2" : "flex-col gap-1"} ${className}`}>
      <label htmlFor={id} className={`text-label ${inline ? "text-fg-muted" : "text-fg"}`}>
        {label}
      </label>
      {children}
      {note && (
        <p id={`${id}-note`} className={`text-caption ${error ? "text-danger-text" : "text-fg-muted"}`}>
          {note}
        </p>
      )}
    </div>
  );
}

export function Select({
  label,
  hint,
  error,
  inline,
  className = "",
  id,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: string; error?: string; inline?: boolean }) {
  const autoId = useId();
  const selectId = id ?? autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} id={selectId} inline={inline} className={className}>
      <select
        id={selectId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${selectId}-note` : undefined}
        className={`h-(--size-control-web) ${FIELD} ${error ? "border-danger-text" : "border-border-strong"}`}
        {...props}
      >
        {children}
      </select>
    </FieldShell>
  );
}

export function TextArea({
  label,
  hint,
  error,
  className = "",
  id,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string; error?: string }) {
  const autoId = useId();
  const areaId = id ?? autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} id={areaId} className={className}>
      <textarea
        id={areaId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${areaId}-note` : undefined}
        className={`min-h-24 py-2 ${FIELD} ${error ? "border-danger-text" : "border-border-strong"}`}
        {...props}
      />
    </FieldShell>
  );
}

/**
 * Переключаемый чип фильтра. Выбранный — заливка `primary` с `on-primary`, как `ChoiceChip` во Flutter (глава 7);
 * состояние — `aria-pressed` и галочка, не только цвет.
 */
export function Chip({
  selected,
  count,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { selected: boolean; count?: number }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={`inline-flex h-(--size-control-web-sm) items-center gap-1.5 rounded-full border px-3 text-label transition-colors duration-(--duration-fast) ${
        selected
          ? "border-primary bg-primary text-on-primary hover:bg-primary-hover"
          : "border-border-strong bg-surface text-fg hover:bg-surface-subtle"
      } ${className}`}
      {...props}
    >
      {selected && (
        <svg viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path d="m3.5 8.5 3 3 6-7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {children}
      {count !== undefined && <span className="text-caption tabular-nums opacity-80">{count}</span>}
    </button>
  );
}

export type BadgeTone = "neutral" | "success" | "warning" | "danger";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-status-unknown-bg text-status-unknown-fg",
  success: "bg-status-green-bg text-status-green-fg",
  warning: "bg-status-yellow-bg text-status-yellow-fg",
  danger: "bg-status-red-bg text-status-red-fg",
};

/** Метка статуса/типа. Цвет дублируется текстом; для SLA рядом — иконка (`SlaBadge`). */
export function Badge({ tone = "neutral", className = "", children }: { tone?: BadgeTone; className?: string; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-caption ${BADGE_TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}
