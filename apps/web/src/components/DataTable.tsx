import { useState } from 'react';

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  total: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
  search?: string;
  onSearch?: (s: string) => void;
  searchPlaceholder?: string;
  onExportCsv?: () => void;
  rowKey: (row: T, i: number) => string;
};

export function DataTable<T>({ columns, rows, total, page, pageSize, onPage, search, onSearch, searchPlaceholder, onExportCsv, rowKey }: Props<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const pages = Math.max(1, Math.ceil(total / pageSize));
  let view = rows;
  const col = columns.find(c => c.key === sortKey);
  if (col?.sortValue) {
    view = [...rows].sort((a, b) => {
      const va = col.sortValue!(a); const vb = col.sortValue!(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
    });
  }
  const toggle = (key: string) => {
    if (sortKey === key) setSortDir(d => (d === 1 ? -1 : 1));
    else { setSortKey(key); setSortDir(1); }
  };
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {onSearch && (
          <input className="rounded border px-3 py-1.5 text-sm" placeholder={searchPlaceholder || 'Search…'}
            value={search || ''} onChange={e => onSearch(e.target.value)} />
        )}
        <span className="ml-auto text-xs text-slate-500">{total} result{total === 1 ? '' : 's'}</span>
        {onExportCsv && <button className="rounded border px-3 py-1.5 text-sm" onClick={onExportCsv}>Export CSV</button>}
      </div>
      <div className="overflow-x-auto rounded-xl border bg-white">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              {columns.map(c => (
                <th key={c.key} className="px-3 py-2">
                  {c.sortValue
                    ? <button className="uppercase tracking-wide" onClick={() => toggle(c.key)}>{c.header}{sortKey === c.key ? (sortDir === 1 ? ' ▲' : ' ▼') : ''}</button>
                    : c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.map((r, i) => (
              <tr key={rowKey(r, i)} className="border-b last:border-0 hover:bg-slate-50">
                {columns.map(c => <td key={c.key} className="px-3 py-2 align-top">{c.render(r)}</td>)}
              </tr>
            ))}
            {!view.length && <tr><td className="px-3 py-6 text-center text-slate-500" colSpan={columns.length}>No rows match.</td></tr>}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <button className="rounded border px-2 py-1 disabled:opacity-40" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Prev</button>
          <span>Page {page} of {pages}</span>
          <button className="rounded border px-2 py-1 disabled:opacity-40" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
        </div>
      )}
    </div>
  );
}

export function toCsv(headers: string[], rows: (string | number | null | undefined)[][]): string {
  const esc = (v: string | number | null | undefined) => {
    const s = v == null ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [headers.map(esc).join(','), ...rows.map(r => r.map(esc).join(','))].join('\n');
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
