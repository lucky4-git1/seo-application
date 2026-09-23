import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { DataTable } from '../components/DataTable';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { api } from '../lib/api';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

type Competitor = { id: string; domain: string; label: string | null; is_active: boolean };

export function CompetitorsPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [domain, setDomain] = useState('');
  const [err, setErr] = useState('');
  const { data, isLoading, error } = useQuery({
    queryKey: ['competitors', orgId, projectId],
    queryFn: () => api.get<{ items: Competitor[] }>(`/api/v1/organizations/${orgId}/projects/${projectId}/competitors`),
  });
  const add = useMutation({
    mutationFn: () => api.post(`/api/v1/organizations/${orgId}/projects/${projectId}/competitors`, { domain }),
    onSuccess: () => { setDomain(''); setErr(''); qc.invalidateQueries({ queryKey: ['competitors', orgId, projectId] }); },
    onError: (e) => setErr((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/organizations/${orgId}/projects/${projectId}/competitors/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['competitors', orgId, projectId] }),
  });

  return (
    <div>
      <h1 className="text-2xl font-bold">Competitors</h1>
      <div className="mt-3 flex items-center gap-2">
        <input className="w-64 rounded border px-3 py-2 text-sm" placeholder="competitor.com" value={domain} onChange={e => setDomain(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') add.mutate(); }} />
        <button className="rounded bg-slate-900 px-4 py-2 text-sm text-white" onClick={() => add.mutate()}>Add competitor</button>
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <div className="mt-4">
        {isLoading ? <Skeleton className="h-40" />
          : error ? <ErrorState message={(error as Error).message} />
          : !(data?.items || []).length ? <EmptyState title="No competitors yet" hint="Add competitor domains to compare keyword overlap." />
          : <DataTable
            columns={[
              { key: 'd', header: 'Domain', render: r => <span className="font-medium">{r.domain}</span>, sortValue: r => r.domain },
              { key: 'l', header: 'Label', render: r => r.label || '–' },
              { key: 'x', header: '', render: r => <span className="flex gap-2"><Link className="underline" to={`/projects/${orgId}/${projectId}/keyword-gap?competitor=${r.id}`}>Gap →</Link><button className="underline text-red-600" onClick={() => remove.mutate(r.id)}>Remove</button></span> },
            ]}
            rows={data?.items || []} total={(data?.items || []).length} page={1} pageSize={100}
            onPage={() => { }} rowKey={r => r.id}
          />}
      </div>
    </div>
  );
}

const BUCKETS = ['', 'missing', 'weak', 'shared', 'strong'];

type GapRow = {
  keyword: string; your_rank: number | null;
  competitor_ranks: Record<string, number | null>; bucket: string;
  search_volume: number | null; difficulty: number | null;
  intent: string | null; opportunity: number | null;
};

export function KeywordGapPage() {
  const { orgId, projectId } = useProjectParams();
  const initialComp = new URLSearchParams(window.location.search).get('competitor') || '';
  const [competitor, setCompetitor] = useState(initialComp);
  const [bucket, setBucket] = useState('');
  const [page, setPage] = useState(1);
  const { data: comps } = useQuery({
    queryKey: ['competitors', orgId, projectId],
    queryFn: () => api.get<{ items: Competitor[] }>(`/api/v1/organizations/${orgId}/projects/${projectId}/competitors`),
  });
  const { data, isLoading, error } = useQuery({
    queryKey: ['gap', orgId, projectId, competitor, bucket, page],
    queryFn: () => seo.gap(orgId, projectId, { ...(competitor ? { competitor_id: competitor } : {}), ...(bucket ? { bucket } : {}), page, page_size: 50 }),
  });
  const compList: { id: string; domain: string }[] = (data as { competitors?: { id: string; domain: string }[] })?.competitors || [];

  return (
    <div>
      <h1 className="text-2xl font-bold">Keyword Gap</h1>
      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        <select className="rounded border px-2 py-1.5" value={competitor} onChange={e => { setCompetitor(e.target.value); setPage(1); }}>
          <option value="">All competitors</option>
          {(comps?.items || []).map(c => <option key={c.id} value={c.id}>{c.domain}</option>)}
        </select>
        <select className="rounded border px-2 py-1.5" value={bucket} onChange={e => { setBucket(e.target.value); setPage(1); }}>
          {BUCKETS.map(b => <option key={b} value={b}>{b || 'All buckets'}</option>)}
        </select>
        <button className="ml-auto underline" onClick={() => seo.gapCsv(orgId, projectId).catch(e => alert((e as Error).message))}>Export CSV</button>
      </div>
      <div className="mt-3">
        {isLoading ? <Skeleton className="h-64" />
          : error ? <ErrorState message={(error as Error).message} />
          : !(data?.items || []).length ? <EmptyState title="No gap data yet" hint="Track keywords and gather SERP data for you and your competitors first." />
          : <DataTable<GapRow>
            columns={[
              { key: 'kw', header: 'Keyword', render: r => r.keyword, sortValue: r => r.keyword },
              { key: 'you', header: 'You', render: r => r.your_rank ?? '–', sortValue: r => r.your_rank ?? 999 },
              ...compList.map(c => ({ key: c.id, header: c.domain, render: (r: GapRow) => r.competitor_ranks[c.id] ?? '–' })),
              { key: 'b', header: 'Bucket', render: r => r.bucket },
              { key: 'opp', header: 'Opportunity', render: r => <b>{r.opportunity?.toFixed(0) ?? '–'}</b>, sortValue: (r: GapRow) => r.opportunity ?? -1 },
            ]}
            rows={(data?.items || []) as GapRow[]} total={data?.total || 0} page={page} pageSize={50}
            onPage={setPage} rowKey={(r: GapRow) => r.keyword}
          />}
      </div>
    </div>
  );
}
