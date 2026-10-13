// Постраничная выгрузка (`PaginationMeta` контракта): все страницы или не больше `maxPages`.

export interface Page<T> {
  items: T[];
  meta: { page: number; total_pages: number; total_items: number };
}

/** Все элементы выборки по страницам 1…N. */
export async function fetchAllPages<T>(load: (page: number) => Promise<Page<T>>): Promise<T[]> {
  return (await fetchPages(load, Number.POSITIVE_INFINITY)).items;
}

/**
 * Не больше `maxPages` страниц (колонка доски — 5 по 100, ADR 0025 п. 8); `total` — размер всей выборки,
 * `truncated` — загружена не вся.
 */
export async function fetchPages<T>(
  load: (page: number) => Promise<Page<T>>,
  maxPages: number,
): Promise<{ items: T[]; total: number; truncated: boolean }> {
  const items: T[] = [];
  let page = 1;
  let result: Page<T>;
  do {
    result = await load(page);
    items.push(...result.items);
    page += 1;
  } while (page <= result.meta.total_pages && page <= maxPages);
  return { items, total: result.meta.total_items, truncated: items.length < result.meta.total_items };
}
