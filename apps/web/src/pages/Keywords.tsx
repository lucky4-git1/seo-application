import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { DataTable, downloadCsv, toCsv } from '../components/DataTable';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

function fmtVol(v: number | null) {
  if (v == null) return '–';
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : `${v}`;
}

export function KeywordsPage() {
  const { orgId, projectId } = useProjectParams();
  const [seed, setSeed] = useState('');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [intent, setIntent] = useState('');
  const [sort, setSort] = useState('opportunity');
  const [researching, setResearching] = useState(false);
  const [err, setErr] = useState('');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['keywords', orgId, projectId, page, search, intent, sort],
    queryFn: () => seo.keywords(orgId, projectId, {
      page, page_size: 50, ...(search ? { search } : {}),
      ...(intent ? { intent } : {}), sort,
    }),
    refetchInterval: researching ? 3000 : false,
  });

  const runResearch = async () => {
    setErr('');
    if (!seed.trim()) { setErr('Enter a seed keyword.'); return; }
    try {
      await seo.research(orgId, projectId, seed.trim());
      setResearching(true);
      setTimeout(() => { setResearching(false); refetch(); }, 45000);
      setTimeout(() => refetch(), 8000);
    } catch (e: unknown) {
      const msg = (e as Error).message;
      setErr(msg.includes('no keyword provider') ? 'Keyword provider not configured. Connect a provider in Settings to enable keyword research.' : msg);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold">Keyword Research</h1>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input className="w-64 rounded border px-3 py-2 text-sm" placeholder="Seed keyword, e.g. running shoes" value={seed} onChange={e => setSeed(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') runResearch(); }} />
        <button className="rounded bg-slate-900 px-4 py-2 text-sm text-white" onClick={runResearch}>Research</button>
        {researching && <span className="text-sm text-blue-700">Research running — results appear below…</span>}
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        <select className="rounded border px-2 py-1.5" value={intent} onChange={e => { setIntent(e.target.value); setPage(1); }}>
          <option value="">All intents</option>
          {['INFORMATIONAL', 'NAVIGATIONAL', 'COMMERCIAL', 'TRANSACTIONAL', 'LOCAL'].map(i => <option key={i} value={i}>{i}</option>)}
        </select>
        <select className="rounded border px-2 py-1.5" value={sort} onChange={e => { setSort(e.target.value); setPage(1); }}>
          <option value="opportunity">Sort: Opportunity</option>
          <option value="volume">Sort: Volume</option>
          <option value="difficulty">Sort: Difficulty</option>
          <option value="keyword">Sort: A–Z</option>
        </select>
      </div>
      <div className="mt-3">
        {isLoading ? <Skeleton className="h-64" />
          : error ? <ErrorState message={(error as Error).message} />
          : !(data?.items || []).length ? <EmptyState title="No keyword data yet" hint="Run keyword research or configure a keyword provider." />
          : <DataTable
            columns={[
              { key: 'kw', header: 'Keyword', render: r => <Link className="underline" to={r.id}>{r.keyword}</Link>, sortValue: r => r.keyword },
              { key: 'intent', header: 'Intent', render: r => r.intent || '–' },
              { key: 'vol', header: 'Volume', render: r => fmtVol(r.search_volume), sortValue: r => r.search_volume ?? -1 },
              { key: 'cpc', header: 'CPC', render: r => r.cpc != null ? `$${r.cpc.toFixed(2)}` : '–', sortValue: r => r.cpc ?? -1 },
              { key: 'diff', header: 'Difficulty', render: r => r.difficulty != null ? r.difficulty.toFixed(0) : '–', sortValue: r => r.difficulty ?? 101 },
              { key: 'opp', header: 'Opportunity', render: r => <b>{r.opportunity != null ? r.opportunity.toFixed(0) : '–'}</b>, sortValue: r => r.opportunity ?? -1 },
            ]}
            rows={data?.items || []} total={data?.total || 0} page={page} pageSize={50}
            onPage={setPage} search={search} onSearch={s => { setSearch(s); setPage(1); }} searchPlaceholder="Filter keywords…"
            onExportCsv={() => {
              const rows = (data?.items || []).map(k => [k.keyword, k.intent, k.search_volume, k.cpc, k.difficulty, k.opportunity, k.provider]);
              downloadCsv('keywords.csv', toCsv(['keyword', 'intent', 'volume', 'cpc', 'difficulty', 'opportunity', 'provider'], rows));
            }}
            rowKey={r => r.id}
          />}
      </div>
      <p className="mt-2 text-xs text-slate-400">Difficulty and Opportunity are platform estimates computed from provider data — see docs for formulas.</p>
    </div>
  );
}

export function KeywordDetailPage() {
  const { orgId, projectId } = useProjectParams();
  const { keywordId } = useParams();
  const id = keywordId || '';
  const { data, isLoading, error } = useQuery({
    queryKey: ['keyword', orgId, projectId, id],
    queryFn: () => seo.keyword(orgId, projectId, id),
    enabled: !!id,
  });
  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !data) return <ErrorState message={(error as Error)?.message || 'Keyword not found'} />;
  const max = Math.max(1, ...(data.trend || [0]));
  return (
    <div>
      <Link className="text-sm underline" to="..">← Keywords</Link>
      <h1 className="mt-1 text-2xl font-bold">{data.keyword}</h1>
      <p className="text-sm text-slate-500">{data.country} · {data.language} · {data.intent || 'intent unknown'} · via {data.provider || '–'}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[['Volume', fmtVol(data.search_volume)], ['CPC', data.cpc != null ? `$${data.cpc.toFixed(2)}` : '–'],
          ['Difficulty', data.difficulty != null ? data.difficulty.toFixed(0) : '–'],
          ['Opportunity', data.opportunity != null ? data.opportunity.toFixed(0) : '–']].map(([l, v]) => (
          <div key={l} className="rounded-xl border bg-white p-4"><div className="text-xs uppercase text-slate-500">{l}</div><div className="text-2xl font-bold">{v}</div></div>
        ))}
      </div>
      <div className="mt-3 rounded-xl border bg-white p-4">
        <h2 className="font-semibold">Trend</h2>
        {!data.trend?.length ? <p className="text-sm text-slate-500">No trend data from provider.</p>
          : <div className="mt-2 flex h-24 items-end gap-1">{data.trend.map((v, i) => (
            <div key={i} className="flex-1 rounded-t bg-slate-800" style={{ height: `${Math.max(4, (v / max) * 100)}%` }} title={`${v}`} />))}</div>}
      </div>
      <div className="mt-3 rounded-xl border bg-white p-4">
        <h2 className="font-semibold">Metric history</h2>
        <table className="mt-2 w-full text-left text-sm">
          <thead><tr className="border-b text-xs uppercase text-slate-500"><th className="py-1">Observed</th><th>Volume</th><th>CPC</th><th>Competition</th><th>Provider</th></tr></thead>
          <tbody>{(data.history || []).map((h, i) => <tr key={i} className="border-b"><td>{new Date(h.observed_at).toLocaleString()}</td><td>{fmtVol(h.search_volume)}</td><td>{h.cpc ?? '–'}</td><td>{h.competition ?? '–'}</td><td>{h.provider}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
