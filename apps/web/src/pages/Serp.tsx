import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { DataTable } from '../components/DataTable';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

export function SerpPage() {
  const { orgId, projectId } = useProjectParams();
  const [keyword, setKeyword] = useState('');
  const [country, setCountry] = useState('US');
  const [device, setDevice] = useState('DESKTOP');
  const [searching, setSearching] = useState(false);
  const [err, setErr] = useState('');
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['serp', orgId, projectId],
    queryFn: () => seo.serpHistory(orgId, projectId),
    refetchInterval: searching ? 4000 : false,
  });

  const run = async () => {
    setErr('');
    if (!keyword.trim()) { setErr('Enter a keyword.'); return; }
    try {
      await seo.serpSearch(orgId, projectId, { keyword: keyword.trim(), country, device });
      setSearching(true);
      setTimeout(() => { setSearching(false); refetch(); }, 60000);
      setTimeout(() => refetch(), 10000);
    } catch (e: unknown) {
      const msg = (e as Error).message;
      setErr(msg.includes('no SERP provider') ? 'SERP provider not configured. Connect a provider in Settings to enable SERP analysis.' : msg);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold">SERP Analysis</h1>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <input className="w-64 rounded border px-3 py-2" placeholder="Keyword" value={keyword} onChange={e => setKeyword(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') run(); }} />
        <input className="w-20 rounded border px-2 py-2" value={country} onChange={e => setCountry(e.target.value.toUpperCase())} title="Country code" />
        <select className="rounded border px-2 py-2" value={device} onChange={e => setDevice(e.target.value)}>
          <option value="DESKTOP">Desktop</option><option value="MOBILE">Mobile</option>
        </select>
        <button className="rounded bg-slate-900 px-4 py-2 text-white" onClick={run}>Search SERP</button>
        {searching && <span className="text-blue-700">Fetching live SERP — history updates below…</span>}
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <div className="mt-4">
        {isLoading ? <Skeleton className="h-40" />
          : error ? <ErrorState message={(error as Error).message} />
          : !(data?.items || []).length ? <EmptyState title="No SERP data yet" hint="Run a SERP search above. A configured provider is required." />
          : <DataTable
            columns={[
              { key: 'kw', header: 'Keyword', render: r => <Link className="underline" to={r.id}>{r.keyword}</Link>, sortValue: r => r.keyword },
              { key: 'geo', header: 'Market', render: r => `${r.country}/${r.language}/${r.device}` },
              { key: 'n', header: 'Results', render: r => `${r.results}`, sortValue: r => r.results },
              { key: 'f', header: 'Features', render: r => `${r.features}` },
              { key: 'when', header: 'Searched', render: r => r.searched_at ? new Date(r.searched_at).toLocaleString() : '–', sortValue: r => r.searched_at || '' },
            ]}
            rows={data?.items || []} total={data?.total || 0} page={1} pageSize={20}
            onPage={() => { }} rowKey={r => r.id}
          />}
      </div>
    </div>
  );
}

export function SerpDetailPage() {
  const { orgId, projectId } = useProjectParams();
  const { searchId } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ['serp-detail', orgId, projectId, searchId],
    queryFn: () => seo.serpDetail(orgId, projectId, searchId || ''),
    enabled: !!searchId,
  });
  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !data) return <ErrorState message={(error as Error)?.message || 'SERP search not found'} />;
  return (
    <div>
      <Link className="text-sm underline" to="..">← SERP history</Link>
      <h1 className="mt-1 text-2xl font-bold">{data.keyword}</h1>
      <p className="text-sm text-slate-500">{data.country}/{data.language}/{data.device} · via {data.provider} · {data.searched_at ? new Date(data.searched_at).toLocaleString() : ''}</p>
      {data.feature_items.length > 0 && (
        <div className="mt-3 rounded-xl border bg-white p-4">
          <h2 className="font-semibold">SERP features ({data.feature_items.length})</h2>
          <div className="mt-1 flex flex-wrap gap-2 text-sm">{data.feature_items.map((f, i) => <span key={i} className="rounded bg-slate-100 px-2 py-0.5">{f.feature_type}{f.position ? ` #${f.position}` : ''}</span>)}</div>
        </div>
      )}
      <div className="mt-3">
        <DataTable
          columns={[
            { key: 'pos', header: '#', render: r => r.position, sortValue: r => r.position },
            { key: 'dom', header: 'Domain', render: r => r.domain },
            { key: 't', header: 'Result', render: r => <span><a className="underline" href={r.url} target="_blank" rel="noreferrer">{r.title || r.url}</a><br /><span className="text-xs text-slate-500">{r.snippet}</span></span> },
            { key: 'type', header: 'Type', render: r => r.result_type },
          ]}
          rows={data.result_items} total={data.result_items.length} page={1} pageSize={100}
          onPage={() => { }} rowKey={r => `${r.position}-${r.url}`}
        />
      </div>
    </div>
  );
}
