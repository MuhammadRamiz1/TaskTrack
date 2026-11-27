import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

export function Pager({
  page,
  pageSize,
  count,
  onPage,
}: {
  page: number;
  pageSize: number;
  count: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (count <= pageSize) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 border-t border-line px-4 py-3">
      <p className="text-sm text-muted">
        Page {page} of {pages} · {count} total
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft /> Previous
        </Button>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next <ChevronRight />
        </Button>
      </div>
    </nav>
  );
}

/** Generic responsive table: real table on md+, stacked cards on phones. */
export function ResponsiveTable<T>({
  rows,
  columns,
  rowKey,
  onRowClick,
  caption,
}: {
  rows: T[];
  columns: { header: string; cell: (row: T) => React.ReactNode; className?: string; mobileHidden?: boolean }[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  caption: string;
}) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-line text-xs uppercase tracking-wide text-muted">
              {columns.map((c) => (
                <th key={c.header} scope="col" className={`px-4 py-3 font-semibold ${c.className ?? ""}`}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={`border-b border-line last:border-0 ${onRowClick ? "cursor-pointer hover:bg-hover" : ""}`}
              >
                {columns.map((c) => (
                  <td key={c.header} className={`px-4 py-3 align-middle ${c.className ?? ""}`}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-line md:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)}>
            <div
              role={onRowClick ? "button" : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(row) : undefined}
              className="flex flex-col gap-1.5 px-4 py-3 active:bg-hover"
            >
              {columns
                .filter((c) => !c.mobileHidden)
                .map((c, i) => (
                  <div key={c.header} className={i === 0 ? "font-semibold text-ink" : "flex items-center justify-between gap-3 text-sm"}>
                    {i > 0 && <span className="text-muted">{c.header}</span>}
                    <span className="min-w-0 text-right">{c.cell(row)}</span>
                  </div>
                ))}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
