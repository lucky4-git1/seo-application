import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';
import { DataTable, downloadCsv, toCsv } from '../components/DataTable';

export function AuditListPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [maxPages, setMaxPages] = useState(200);
  const { data, isLoading, error } = useQuery({
    queryKey: ['audits', orgId, projectId],
    queryFn: () => seo.audits(orgId, projectId),
    refetchInterval: (q) => (q.state.data?.items || []).some(r => r.status === 'PENDING' || r.status === 'RUNNING') ? 4000 : false,
  });
  const start = useMutation({
    mutationFn: () => seo.startAudit(orgId, projectId, maxPages),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['audits', orgId, projectId] }),
  });

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Site Audit</h1>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <label>Max pages <input type="number" min={1} max={500} value={maxPages} onChange={e => setMaxPages(Number(e.target.value))} className="w-20 rounded border px-2 py-1" /></label>
          <button className="rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50" disabled={start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? 'Starting…' : 'Run Audit'}
          </button>
        </div>
      </div>
      {start.isError && <p className="mt-2 text-sm text-red-600">{(start.error as Error).message}</p>}
      {isLoading ? <Skeleton className="mt-4 h-40" />
        : error ? <ErrorState message={(error as Error).message} />
        : !(data?.items || []).length ? <div className="mt-4"><EmptyState title="No site audit yet" hint="Run your first technical SEO audit." /></div>
        : <div className="mt-4">
          <DataTable
            columns={[
              { key: 'date', header: 'Started', render: r => new Date(r.created_at || '').toLocaleString(), sortValue: r => r.created_at || '' },
              { key: 'status', header: 'Status', render: r => r.status },
              { key: 'score', header: 'Health', render: r => r.health_score != null ? `${r.health_score}` : '–', sortValue: r => r.health_score ?? -1 },
              { key: 'pages', header: 'Pages', render: r => `${r.pages_crawled}`, sortValue: r => r.pages_crawled },
              { key: 'issues', header: 'Issues', render: r => `${r.issues_found}`, sortValue: r => r.issues_found },
              { key: 'open', header: '', render: r => <Link className="underline" to={r.id}>Open →</Link> },
            ]}
            rows={data?.items || []} total={data?.total || 0} page={data?.page || 1} pageSize={data?.page_size || 20}
            onPage={() => { }} rowKey={r => r.id}
          />
        </div>}
    </div>
  );
}

const SEV_ORDER: Record<string, number> = { CRITICAL: 0, ERROR: 1, WARNING: 2, NOTICE: 3 };

export function AuditDetailPage() {
  const { orgId, projectId } = useProjectParams();
  const { runId } = useParams();
  const rid = runId || '';
  const [page, setPage] = useState(1);
  const [sev, setSev] = useState('');
  const [cat, setCat] = useState('');
  const [search, setSearch] = useState('');
  const { data: run, isLoading, error } = useQuery({
    queryKey: ['audit', orgId, projectId, rid],
    queryFn: () => seo.audit(orgId, projectId, rid),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'PENDING' || s === 'RUNNING' ? 3000 : false;
    },
  });
  const { data: issues } = useQuery({
    queryKey: ['issues', orgId, projectId, rid, page, sev, cat, search],
    queryFn: () => seo.issues(orgId, projectId, rid, { page, page_size: 20, ...(sev ? { severity: sev } : {}), ...(cat ? { category: cat } : {}), ...(search ? { search } : {}) }),
    enabled: run?.status === 'COMPLETED',
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !run) return <ErrorState message={(error as Error)?.message || 'Audit not found'} />;
  if (run.status !== 'COMPLETED') {
    return (
      <div>
        <h1 className="text-2xl font-bold">Audit {run.status.toLowerCase()}…</h1>
        <p className="mt-2 text-sm text-slate-500">Pages discovered: {run.pages_discovered} · crawled: {run.pages_crawled}. This page refreshes automatically.</p>
        {run.error && <p className="mt-2 text-sm text-red-600">{run.error}</p>}
      </div>
    );
  }
  return (
    <div>
      <Link className="text-sm underline" to="..">← All audits</Link>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Health {run.health_score}/100</h1>
        <span className="text-sm text-slate-500">{run.pages_crawled} pages · {run.rules_firing} rules firing · {run.issues_found} affected URLs</span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(run.buckets).map(([b, v]) => (
          <div key={b} className="rounded-xl border bg-white p-3">
            <div className="text-xs uppercase text-slate-500">{b}</div>
            <div className="text-xl font-bold">{v}</div>
            <div className="mt-1 h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-slate-900" style={{ width: `${v}%` }} /></div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        <select className="rounded border px-2 py-1.5" value={sev} onChange={e => { setSev(e.target.value); setPage(1); }}>
          <option value="">All severities</option>{['CRITICAL', 'ERROR', 'WARNING', 'NOTICE'].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="rounded border px-2 py-1.5" value={cat} onChange={e => { setCat(e.target.value); setPage(1); }}>
          <option value="">All categories</option>
          {['Crawlability', 'Indexability', 'Metadata', 'Content', 'Links', 'Images', 'Canonical', 'Redirects', 'HTTPS', 'Structured Data', 'Performance', 'International'].map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="mt-3">
        <DataTable
          columns={[
            { key: 'sev', header: 'Severity', render: r => r.severity, sortValue: r => SEV_ORDER[r.severity] ?? 9 },
            { key: 'rule', header: 'Rule', render: r => <span><span className="font-mono text-xs">{r.rule_code}</span><br />{r.rule_name}</span> },
            { key: 'msg', header: 'Finding', render: r => <span>{r.message}<br /><span className="text-xs text-slate-500">{r.recommendation}</span></span> },
            { key: 'n', header: 'URLs', render: r => <IssueUrls orgId={orgId} projectId={projectId} issue={r} />, sortValue: r => r.affected_count },
          ]}
          rows={issues?.items || []} total={issues?.total || 0} page={page} pageSize={20}
          onPage={setPage} search={search} onSearch={s => { setSearch(s); setPage(1); }} searchPlaceholder="Search issues…"
          onExportCsv={() => {
            const rows = (issues?.items || []).map(i => [i.severity, i.rule_code, i.rule_name, i.message, i.affected_count, i.recommendation]);
            downloadCsv(`audit-${rid}-issues.csv`, toCsv(['severity', 'rule', 'name', 'message', 'urls', 'recommendation'], rows));
          }}
          rowKey={r => r.id}
        />
      </div>
    </div>
  );
}

function IssueUrls({ orgId, projectId, issue }: { orgId: string; projectId: string; issue: { id: string; affected_count: number } }) {
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ['issue-urls', issue.id], enabled: open,
    queryFn: () => seo.issueUrls(orgId, projectId, issue.id, 1, 20),
  });
  if (!open) return <button className="underline" onClick={() => setOpen(true)}>{issue.affected_count} URLs</button>;
  return (
    <div className="max-w-md">
      <button className="underline" onClick={() => setOpen(false)}>hide</button>
      <ul className="mt-1 max-h-40 list-disc overflow-auto pl-5 text-xs">
        {(data?.items || []).map(u => <li key={u.url} className="break-all"><a className="underline" href={u.url} target="_blank" rel="noreferrer">{u.url}</a></li>)}
      </ul>
      {(data?.total || 0) > 20 && <p className="text-xs text-slate-400">showing 20 of {data?.total}</p>}
    </div>
  );
}
