import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { DataTable } from '../components/DataTable';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

type Reco = {
  id: string; type: string; source: string; severity: string; impact: number;
  effort: number; confidence: number; score: number; title: string;
  description: string; why: string; recommended_action: string;
  related_url: string | null; related_keyword: string | null; status: string;
};

const SEVC = { CRITICAL: 'bg-red-700 text-white', ERROR: 'bg-red-100 text-red-800', WARNING: 'bg-amber-100 text-amber-800', NOTICE: 'bg-slate-100 text-slate-600' } as Record<string, string>;

function RecoRow({ r, onStatus }: { r: Reco; onStatus: (id: string, s: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${SEVC[r.severity] || 'bg-slate-100'}`}>{r.severity}</span>
        <span className="font-medium">{r.title}</span>
        <span className="ml-auto text-sm font-bold">{r.score.toFixed(0)}</span>
      </div>
      <p className="mt-1 text-sm text-slate-600">{r.description}</p>
      {open && (
        <div className="mt-2 text-sm">
          <p><b>Why:</b> {r.why}</p>
          <p className="mt-1"><b>Action:</b> {r.recommended_action}</p>
          <p className="mt-1 text-xs text-slate-500">Type {r.type} · Source {r.source} · Impact {r.impact} · Effort {r.effort} · Confidence {r.confidence}</p>
          {r.related_url && <p className="mt-1 text-xs"><a className="break-all underline" href={r.related_url} target="_blank" rel="noreferrer">{r.related_url}</a></p>}
        </div>
      )}
      <div className="mt-2 flex gap-2 text-xs">
        <button className="underline" onClick={() => setOpen(!open)}>{open ? 'less' : 'details'}</button>
        {r.status === 'OPEN' && <><button className="underline" onClick={() => onStatus(r.id, 'IN_PROGRESS')}>Start</button><button className="underline" onClick={() => onStatus(r.id, 'DISMISSED')}>Dismiss</button><button className="underline" onClick={() => onStatus(r.id, 'COMPLETED')}>Done</button></>}
        {r.status === 'IN_PROGRESS' && <><button className="underline" onClick={() => onStatus(r.id, 'COMPLETED')}>Done</button><button className="underline" onClick={() => onStatus(r.id, 'OPEN')}>Reopen</button></>}
        {(r.status === 'DISMISSED' || r.status === 'COMPLETED') && <button className="underline" onClick={() => onStatus(r.id, 'OPEN')}>Reopen</button>}
        <span className="ml-auto text-slate-400">{r.status}</span>
      </div>
    </div>
  );
}

export function RecommendationsPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [source, setSource] = useState('');
  const [show, setShow] = useState('OPEN');
  const [recalculating, setRecalculating] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['recos', orgId, projectId, source, show],
    queryFn: () => seo.recommendations(orgId, projectId, { page: 1, page_size: 100, ...(source ? { source } : {}), status: show }),
    refetchInterval: recalculating ? 4000 : false,
  });
  const setStatus = useMutation({
    mutationFn: ({ id, s }: { id: string; s: string }) => seo.recoStatus(id, s),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recos', orgId, projectId] }),
  });
  const recalc = async () => {
    await seo.recalculate(orgId, projectId);
    setRecalculating(true);
    setTimeout(() => { setRecalculating(false); refetch(); }, 30000);
    setTimeout(() => refetch(), 8000);
  };

  const items: Reco[] = (data?.items || []) as Reco[];
  const high = items.filter(r => r.score >= 70);
  const quick = items.filter(r => r.effort <= 1.5 && r.impact >= 6 && r.score < 70);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-bold">Action Center</h1>
        <button className="ml-auto rounded bg-slate-900 px-3 py-1.5 text-sm text-white" onClick={recalc}>Recalculate</button>
      </div>
      {recalculating && <p className="mt-1 text-sm text-blue-700">Recalculating from audit, GSC, keyword, rank and gap data…</p>}
      <div className="mt-2 flex flex-wrap gap-2 text-sm">
        {['OPEN', 'IN_PROGRESS', 'DISMISSED', 'COMPLETED'].map(s => (
          <button key={s} className={`rounded border px-2 py-1 ${show === s ? 'bg-slate-900 text-white' : ''}`} onClick={() => setShow(s)}>{s} ({(data?.by_status as Record<string, number> | undefined)?.[s] ?? 0})</button>
        ))}
        <select className="rounded border px-2 py-1" value={source} onChange={e => setSource(e.target.value)}>
          <option value="">All sources</option>
          {['AUDIT', 'GSC', 'KEYWORDS', 'RANK_TRACKING', 'GAP'].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {isLoading ? <Skeleton className="mt-3 h-64" />
        : error ? <ErrorState message={(error as Error).message} />
        : !items.length ? <div className="mt-3"><EmptyState title="No recommendations yet" hint="Run an audit, sync Search Console, or research keywords, then recalculate." /></div>
        : (
          <div className="mt-3 space-y-4">
            {show === 'OPEN' && high.length > 0 && (
              <section><h2 className="font-semibold">High priority</h2>
                <div className="mt-2 space-y-2">{high.map(r => <RecoRow key={r.id} r={r} onStatus={(id, s) => setStatus.mutate({ id, s })} />)}</div>
              </section>
            )}
            {show === 'OPEN' && quick.length > 0 && (
              <section><h2 className="font-semibold">Quick wins</h2>
                <div className="mt-2 space-y-2">{quick.map(r => <RecoRow key={r.id} r={r} onStatus={(id, s) => setStatus.mutate({ id, s })} />)}</div>
              </section>
            )}
            <section><h2 className="font-semibold">{show === 'OPEN' ? 'All open' : show.toLowerCase().replace('_', ' ')}</h2>
              <div className="mt-2 space-y-2">{items.map(r => <RecoRow key={r.id} r={r} onStatus={(id, s) => setStatus.mutate({ id, s })} />)}</div>
            </section>
          </div>
        )}
      <p className="mt-3 text-xs text-slate-400">Priority = impact × confidence × 10 ÷ effort. Only measured data feeds the engine — nothing is invented.</p>
    </div>
  );
}
