import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { DataTable } from '../components/DataTable';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

function Change({ v }: { v: number | null }) {
  if (v == null || v === 0) return <span className="text-slate-400">–</span>;
  return <span className={v > 0 ? 'text-green-700' : 'text-red-600'}>{v > 0 ? `▲ ${v}` : `▼ ${-v}`}</span>;
}

function Spark({ points }: { points: (number | null)[] }) {
  const vals = points.filter((v): v is number => v != null);
  if (!vals.length) return <span className="text-slate-300">no data</span>;
  const min = Math.min(...vals); const max = Math.max(...vals);
  const span = Math.max(1, max - min);
  const pts = vals.map((v, i) => `${(i / Math.max(1, vals.length - 1)) * 100},${30 - ((v - min) / span) * 26}`).join(' ');
  return <svg width="100" height="32"><polyline points={pts} fill="none" stroke="#0f172a" strokeWidth="1.5" /></svg>;
}

export function RankingsPage() {
  const { orgId, projectId } = useProjectParams();
  const [keyword, setKeyword] = useState('');
  const [err, setErr] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['tracked', orgId, projectId],
    queryFn: () => seo.tracked(orgId, projectId),
  });

  const add = async () => {
    setErr('');
    if (!keyword.trim()) { setErr('Enter a keyword.'); return; }
    try {
      await seo.trackKeyword(orgId, projectId, { keyword: keyword.trim() });
      setKeyword('');
      setTimeout(() => refetch(), 5000);
      refetch();
    } catch (e: unknown) {
      const msg = (e as Error).message;
      setErr(msg.includes('no SERP provider') ? 'SERP provider not configured. Connect a provider in Settings to track rankings.' : msg);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold">Position Tracking</h1>
      <div className="mt-3 flex items-center gap-2">
        <input className="w-64 rounded border px-3 py-2 text-sm" placeholder="Add keyword to track" value={keyword} onChange={e => setKeyword(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') add(); }} />
        <button className="rounded bg-slate-900 px-4 py-2 text-sm text-white" onClick={add}>Track</button>
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <div className="mt-4">
        {isLoading ? <Skeleton className="h-64" />
          : error ? <ErrorState message={(error as Error).message} />
          : !(data?.items || []).length ? <EmptyState title="No tracked keywords yet" hint="Add keywords to begin monitoring your search visibility." />
          : <DataTable
            columns={[
              { key: 'kw', header: 'Keyword', render: r => r.keyword, sortValue: r => r.keyword },
              { key: 'cur', header: 'Rank', render: r => r.current_rank ?? '–', sortValue: r => r.current_rank ?? 999 },
              { key: 'chg', header: 'Change', render: r => <Change v={r.change} />, sortValue: r => r.change ?? 0 },
              { key: 'best', header: 'Best', render: r => r.best_rank ?? '–', sortValue: r => r.best_rank ?? 999 },
              { key: 'worst', header: 'Worst', render: r => r.worst_rank ?? '–' },
              { key: 'trend', header: 'Trend', render: r => <HistorySpark orgId={orgId} projectId={projectId} id={r.id} show={expanded === r.id} /> },
              { key: 'x', header: '', render: r => <button className="underline" onClick={() => setExpanded(expanded === r.id ? null : r.id)}>{expanded === r.id ? 'hide' : 'history'}</button> },
            ]}
            rows={data?.items || []} total={data?.total || 0} page={1} pageSize={100}
            onPage={() => { }} rowKey={r => r.id}
          />}
      </div>
    </div>
  );
}

function HistorySpark({ orgId, projectId, id, show }: { orgId: string; projectId: string; id: string; show: boolean }) {
  const { data } = useQuery({
    queryKey: ['rank-history', id], enabled: show,
    queryFn: () => seo.rankHistory(orgId, projectId, id),
  });
  if (!show) return <span className="text-slate-300">–</span>;
  if (!data) return <span className="text-slate-300">…</span>;
  return <Spark points={data.items.map(o => o.rank)} />;
}
