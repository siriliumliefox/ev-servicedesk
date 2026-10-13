// Переключатель страниц выборки (`PaginationMeta` контракта): «назад», «страница N из M», «вперёд».
// Одна страница — не показывается. Подписи кнопок — по смыслу ленты (лента публикаций: «Новее» / «Старее»).
import { Button } from "../components";
import { formatInt } from "../data/format.ts";

export interface PagerProps {
  meta: { page: number; total_pages: number; total_items: number };
  onPage: (page: number) => void;
  label: string;
  prev?: string;
  next?: string;
}

export function Pager({ meta, onPage, label, prev = "Назад", next = "Вперёд" }: PagerProps) {
  if (meta.total_pages <= 1) return null;
  return (
    <nav aria-label={label} className="flex items-center gap-3 text-body-sm">
      <Button size="sm" variant="secondary" disabled={meta.page <= 1} onClick={() => onPage(meta.page - 1)}>
        {prev}
      </Button>
      <span>
        Страница {meta.page} из {meta.total_pages} · всего {formatInt(meta.total_items)}
      </span>
      <Button size="sm" variant="secondary" disabled={meta.page >= meta.total_pages} onClick={() => onPage(meta.page + 1)}>
        {next}
      </Button>
    </nav>
  );
}
