import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { DataTable } from '../components/DataTable';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

export function GscPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [days, setDays] = useState(28);
  const [qPage, setQPage] = useState(1);
  const [qSearch, setQSearch] = useState('');
  const [pPage, setPPage] = useState(1);
  const [pSearch, setPSearch] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [err, setErr] = useState('');

  const { data: conns, refetch: refetchConns } = useQuery({
    queryKey: ['gsc-conns', orgId, projectId],
    queryFn: () => seo.gscConnections(orgId, projectId),
  });
  const selected = (conns?.items || []).flatMap(c => c.properties).find(p => p.is_selected);

  const { data: ov, isLoading, error, refetch } = useQuery({
    queryKey: ['gsc-overview', orgId, projectId, days],
    queryFn: () => seo.gscOverview(orgId, projectId, days),
    retry: false,
    refetchInterval: syncing ? 5000 : false,
  });
  const noProperty = (error as Error | null)?.message?.includes('No Search Console property');

  const { data: queries } = useQuery({
    queryKey: ['gsc-queries', orgId, projectId, days, qPage, qSearch],
    queryFn: () => seo.gscQueries(orgId, projectId, { days, page: qPage, page_size: 25, ...(qSearch ? { search: qSearch } : {}) }),
    enabled: !!selected,
  });
  const { data: pages } = useQuery({
    queryKey: ['gsc-pages', orgId, projectId, days, pPage, pSearch],
    queryFn: () => seo.gscPages(orgId, projectId, { days, page: pPage, page_size: 25, ...(pSearch ? { search: pSearch } : {}) }),
    enabled: !!selected,
  });

  const connect = async () => {
    setErr('');
    try {
      const { auth_url } = await seo.gscAuthUrl(orgId, projectId);
      window.open(auth_url, '_blank', 'width=600,height=700');
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const select = useMutation({
    mutationFn: (id: string) => seo.gscSelect(orgId, projectId, id),
    onSuccess: () => { refetchConns(); refetch(); },
    onError: (e) => setErr((e as Error).message),
  });
  const sync = async () => {
    setErr('');
    try {
      await seo.gscSync(orgId, projectId, undefined, 90);
      setSyncing(true);
      setTimeout(() => { setSyncing(false); refetch(); refetchConns(); }, 90000);
      setTimeout(() => refetch(), 15000);
    } catch (e) { setErr((e as Error).message); }
  };

  const maxImp = Math.max(1, ...(ov?.daily || []).map(d => d.impressions));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-bold">Search Console</h1>
        <div className="ml-auto flex gap-2 text-sm">
          <select className="rounded border px-2 py-1.5" value={days} onChange={e => setDays(Number(e.target.value))}>
            {[7, 28, 90].map(d => <option key={d} value={d}>{d} days</option>)}
          </select>
          {selected && <button className="rounded bg-slate-900 px-3 py-1.5 text-white" onClick={sync}>Sync now</button>}
          <button className="rounded border px-3 py-1.5" onClick={() => refetchConns()}>Refresh</button>
        </div>
      </div>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      {syncing && <p className="mt-2 text-sm text-blue-700">Sync running — data refreshes below…</p>}

      <div className="mt-3 rounded-xl border bg-white p-4 text-sm">
        <h2 className="font-semibold">Connection</h2>
        {!(conns?.items || []).length ? (
          <div className="mt-2">
            <p className="text-slate-500">Connect Search Console to import real queries, clicks and impressions.</p>
            <button className="mt-2 rounded bg-slate-900 px-4 py-2 text-white" onClick={connect}>Connect Google</button>
          </div>
        ) : (
          <div className="mt-2 space-y-2">
            {conns!.items.map(c => (
              <div key={c.id}>
                <span className="font-medium">{c.google_account || 'Google account'}</span>
                <span className="ml-2 text-xs text-slate-500">{c.status}</span>
                <ul className="mt-1 space-y-1">
                  {c.properties.map(p => (
                    <li key={p.id} className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs">{p.site_url}</span>
                      {p.is_selected
                        ? <span className="rounded bg-green-100 px-2 py-0.5 text-xs text-green-800">selected</span>
                        : <button className="text-xs underline" onClick={() => select.mutate(p.id)}>Select for this project</button>}
                      {p.last_synced_at && <span className="text-xs text-slate-400">synced {new Date(p.last_synced_at).toLocaleString()}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <button className="text-xs underline" onClick={connect}>Connect another account</button>
          </div>
        )}
      </div>

      {!selected ? <div className="mt-3"><EmptyState title="No property selected" hint="Select a Search Console property above to see performance data." /></div>
        : isLoading ? <Skeleton className="mt-3 h-64" />
        : noProperty || error || !ov ? <ErrorState message={(error as Error)?.message || 'Failed to load'} />
        : (
          <div className="mt-3">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[['Clicks', ov.queries.clicks.toLocaleString()], ['Impressions', ov.queries.impressions.toLocaleString()],
                ['CTR', `${(ov.queries.ctr * 100).toFixed(1)}%`], ['Avg position', ov.queries.avg_position]].map(([l, v]) => (
                <div key={l} className="rounded-xl border bg-white p-4"><div className="text-xs uppercase text-slate-500">{l}</div><div className="text-2xl font-bold">{v}</div></div>
              ))}
            </div>
            <div className="mt-3 rounded-xl border bg-white p-4">
              <h2 className="font-semibold">Impressions</h2>
              <div className="mt-2 flex h-24 items-end gap-px">
                {ov.daily.map(d => <div key={d.date} className="flex-1 rounded-t bg-slate-800" style={{ height: `${Math.max(3, (d.impressions / maxImp) * 100)}%` }} title={`${d.date}: ${d.impressions}`} />)}
              </div>
            </div>
            <div className="mt-3">
              <h2 className="font-semibold">Top queries</h2>
              <DataTable
                columns={[
                  { key: 'q', header: 'Query', render: r => r.query, sortValue: r => r.query },
                  { key: 'c', header: 'Clicks', render: r => r.clicks.toLocaleString(), sortValue: r => r.clicks },
                  { key: 'i', header: 'Impressions', render: r => r.impressions.toLocaleString(), sortValue: r => r.impressions },
                  { key: 'ctr', header: 'CTR', render: r => `${(r.ctr * 100).toFixed(1)}%`, sortValue: r => r.ctr },
                  { key: 'p', header: 'Position', render: r => r.position, sortValue: r => r.position },
                ]}
                rows={queries?.items || []} total={queries?.total || 0} page={qPage} pageSize={25}
                onPage={setQPage} search={qSearch} onSearch={s => { setQSearch(s); setQPage(1); }} searchPlaceholder="Filter queries…"
                rowKey={r => r.query}
              />
            </div>
            <div className="mt-3">
              <h2 className="font-semibold">Top pages</h2>
              <DataTable
                columns={[
                  { key: 'p', header: 'Page', render: r => <a className="break-all underline" href={r.page} target="_blank" rel="noreferrer">{r.page}</a> },
                  { key: 'c', header: 'Clicks', render: r => r.clicks.toLocaleString(), sortValue: r => r.clicks },
                  { key: 'i', header: 'Impressions', render: r => r.impressions.toLocaleString(), sortValue: r => r.impressions },
                  { key: 'pos', header: 'Position', render: r => r.position, sortValue: r => r.position },
                ]}
                rows={pages?.items || []} total={pages?.total || 0} page={pPage} pageSize={25}
                onPage={setPPage} search={pSearch} onSearch={s => { setPSearch(s); setPPage(1); }} searchPlaceholder="Filter pages…"
                rowKey={r => r.page}
              />
            </div>
          </div>
        )}
    </div>
  );
}
