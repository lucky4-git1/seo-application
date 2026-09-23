import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

const TYPES = ['SEO_OVERVIEW', 'AUDIT', 'KEYWORDS', 'RANKINGS', 'COMPETITORS'];

export function ReportsPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [type, setType] = useState('SEO_OVERVIEW');
  const [format, setFormat] = useState('CSV');
  const [err, setErr] = useState('');
  const { data, isLoading, error } = useQuery({
    queryKey: ['reports', orgId, projectId],
    queryFn: () => seo.reports(orgId, projectId),
    refetchInterval: (q) => (q.state.data?.items || []).some(r => r.status === 'PENDING') ? 4000 : false,
  });
  const create = useMutation({
    mutationFn: () => seo.createReport(orgId, projectId, type, format),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['reports', orgId, projectId] }); },
    onError: (e) => setErr((e as Error).message),
  });
  const download = async (exportId: string, repType: string, fmt: string) => {
    try {
      await seo.reportDownload(orgId, projectId, exportId, `report-${repType.toLowerCase()}.${fmt.toLowerCase()}`);
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold">Reports</h1>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <select className="rounded border px-2 py-2" value={type} onChange={e => setType(e.target.value)}>
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className="rounded border px-2 py-2" value={format} onChange={e => setFormat(e.target.value)}>
          <option value="CSV">CSV</option><option value="PDF">PDF</option>
        </select>
        <button className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50" disabled={create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? 'Queueing…' : 'Generate report'}
        </button>
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <div className="mt-4">
        {isLoading ? <Skeleton className="h-40" />
          : error ? <ErrorState message={(error as Error).message} />
          : !(data?.items || []).length ? <EmptyState title="No reports yet" hint="Generate your first SEO report above. Reports build in the background." />
          : <div className="space-y-2">{(data?.items || []).map(r => (
            <div key={r.id} className="flex flex-wrap items-center gap-2 rounded-xl border bg-white p-3 text-sm">
              <span className="font-medium">{r.type}</span>
              <span className="text-slate-500">{r.status}</span>
              {r.error && <span className="text-red-600">{r.error}</span>}
              <span className="ml-auto flex gap-2">
                {(r.exports || []).map(e => e.status === 'READY'
                  ? <button key={e.id} className="underline" onClick={() => download(e.id, r.type, e.format)}>Download {e.format}</button>
                  : <span key={e.id} className="text-slate-400">{e.format}: {e.status}…</span>)}
              </span>
            </div>
          ))}</div>}
      </div>
    </div>
  );
}
