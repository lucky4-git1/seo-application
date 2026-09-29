import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo, CrawlPageRow } from '../lib/seo';
import { useProjectParams } from '../routes';
import { DataTable, downloadCsv, toCsv } from '../components/DataTable';

const SEV_ORDER: Record<string, number> = { CRITICAL: 0, ERROR: 1, WARNING: 2, NOTICE: 3 };

function StatusBadge({ code }: { code: number | null }) {
  if (!code) return <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">None</span>;
  if (code >= 200 && code < 300) return <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800">{code}</span>;
  if (code >= 300 && code < 400) return <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800">{code}</span>;
  if (code >= 400 && code < 500) return <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">{code}</span>;
  return <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-800">{code}</span>;
}

function IndexabilityBadge({ status }: { status: string }) {
  if (status === 'INDEXABLE') return <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800">Indexable</span>;
  if (status === 'NOINDEX') return <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">Noindex</span>;
  if (status === 'REDIRECTED') return <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800">Redirect</span>;
  if (status === 'BROKEN') return <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-800">Broken</span>;
  if (status === 'ROBOTS_BLOCKED') return <span className="rounded bg-purple-100 px-1.5 py-0.5 text-xs font-medium text-purple-800">Robots</span>;
  return <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{status}</span>;
}

export function AuditListPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [auditMode, setAuditMode] = useState<'quick' | 'standard' | 'custom'>('quick');
  const [customPages, setCustomPages] = useState(100);

  const maxPages = auditMode === 'quick' ? 100 : auditMode === 'standard' ? 500 : customPages;

  const { data, isLoading, error } = useQuery({
    queryKey: ['audits', orgId, projectId],
    queryFn: () => seo.audits(orgId, projectId),
    refetchInterval: (q) => (q.state.data?.items || []).some(r => r.status === 'PENDING' || r.status === 'RUNNING') ? 2000 : false,
  });

  const start = useMutation({
    mutationFn: () => seo.startAudit(orgId, projectId, maxPages),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['audits', orgId, projectId] }),
  });

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-bold">Site Audit</h1>
          <p className="text-xs text-slate-500">Real on-page crawler and technical SEO evaluation</p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <div className="flex rounded border bg-slate-50 p-0.5 text-xs">
            <button
              className={`rounded px-2.5 py-1 ${auditMode === 'quick' ? 'bg-white font-semibold shadow-sm text-slate-900' : 'text-slate-600'}`}
              onClick={() => setAuditMode('quick')}
            >
              Quick (100)
            </button>
            <button
              className={`rounded px-2.5 py-1 ${auditMode === 'standard' ? 'bg-white font-semibold shadow-sm text-slate-900' : 'text-slate-600'}`}
              onClick={() => setAuditMode('standard')}
            >
              Standard (500)
            </button>
            <button
              className={`rounded px-2.5 py-1 ${auditMode === 'custom' ? 'bg-white font-semibold shadow-sm text-slate-900' : 'text-slate-600'}`}
              onClick={() => setAuditMode('custom')}
            >
              Custom
            </button>
          </div>
          {auditMode === 'custom' && (
            <input
              type="number"
              min={1}
              max={500}
              value={customPages}
              onChange={e => setCustomPages(Number(e.target.value))}
              className="w-20 rounded border px-2 py-1 text-xs"
            />
          )}
          <button
            className="rounded bg-slate-900 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
            disabled={start.isPending}
            onClick={() => start.mutate()}
          >
            {start.isPending ? 'Starting…' : 'Run Audit'}
          </button>
        </div>
      </div>
      {start.isError && (
        <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {(start.error as Error).message}
        </div>
      )}
      {isLoading ? <Skeleton className="mt-4 h-40" />
        : error ? <ErrorState message={(error as Error).message} />
        : !(data?.items || []).length ? <div className="mt-4"><EmptyState title="No site audit yet" hint="Run your first technical SEO audit to discover issues and score health." /></div>
        : <div className="mt-4">
          <DataTable
            columns={[
              { key: 'date', header: 'Started', render: r => new Date(r.created_at || '').toLocaleString(), sortValue: r => r.created_at || '' },
              {
                key: 'status',
                header: 'Status',
                render: r => (
                  <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                    r.status === 'COMPLETED' ? 'bg-green-100 text-green-800' :
                    r.status === 'RUNNING' || r.status === 'PENDING' ? 'bg-blue-100 text-blue-800 animate-pulse' :
                    r.status === 'CANCELLED' ? 'bg-slate-100 text-slate-600' : 'bg-red-100 text-red-800'
                  }`}>
                    {r.status}
                  </span>
                )
              },
              { key: 'score', header: 'Health', render: r => r.health_score != null ? `${r.health_score}/100` : '–', sortValue: r => r.health_score ?? -1 },
              { key: 'pages', header: 'Pages', render: r => `${r.pages_crawled}`, sortValue: r => r.pages_crawled },
              { key: 'issues', header: 'Issues', render: r => `${r.issues_found}`, sortValue: r => r.issues_found },
              { key: 'open', header: '', render: r => <Link className="text-xs font-medium text-blue-600 underline" to={r.id}>Open →</Link> },
            ]}
            rows={data?.items || []} total={data?.total || 0} page={data?.page || 1} pageSize={data?.page_size || 20}
            onPage={() => { }} rowKey={r => r.id}
          />
        </div>}
    </div>
  );
}

export function AuditDetailPage() {
  const { orgId, projectId } = useProjectParams();
  const { runId } = useParams();
  const rid = runId || '';
  const qc = useQueryClient();

  const [activeTab, setActiveTab] = useState<'issues' | 'pages'>('issues');
  const [page, setPage] = useState(1);
  const [pagesPage, setPagesPage] = useState(1);
  const [sev, setSev] = useState('');
  const [cat, setCat] = useState('');
  const [search, setSearch] = useState('');
  const [pagesSearch, setPagesSearch] = useState('');
  const [pagesStatus, setPagesStatus] = useState<number | undefined>(undefined);

  const { data: run, isLoading, error } = useQuery({
    queryKey: ['audit', orgId, projectId, rid],
    queryFn: () => seo.audit(orgId, projectId, rid),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'PENDING' || s === 'RUNNING' ? 1500 : false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => seo.cancelAudit(orgId, projectId, rid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['audit', orgId, projectId, rid] }),
  });

  const { data: issues } = useQuery({
    queryKey: ['issues', orgId, projectId, rid, page, sev, cat, search],
    queryFn: () => seo.issues(orgId, projectId, rid, { page, page_size: 20, ...(sev ? { severity: sev } : {}), ...(cat ? { category: cat } : {}), ...(search ? { search } : {}) }),
    enabled: run?.status === 'COMPLETED' && activeTab === 'issues',
  });

  const { data: pagesData } = useQuery({
    queryKey: ['audit-pages', orgId, projectId, rid, pagesPage, pagesSearch, pagesStatus],
    queryFn: () => seo.pages(orgId, projectId, rid, {
      page: pagesPage,
      page_size: 20,
      ...(pagesSearch ? { search: pagesSearch } : {}),
      ...(pagesStatus ? { status_code: pagesStatus } : {}),
    }),
    enabled: (run?.status === 'COMPLETED' || run?.status === 'CANCELLED') && activeTab === 'pages',
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !run) return <ErrorState message={(error as Error)?.message || 'Audit not found'} />;

  // In-progress view
  if (run.status === 'PENDING' || run.status === 'RUNNING') {
    const crawled = run.pages_crawled || 0;
    const discovered = run.pages_discovered || 1;
    const progressPct = Math.min(100, Math.round((crawled / Math.max(crawled, discovered, 10)) * 100));

    return (
      <div className="rounded-xl border bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="h-3 w-3 animate-ping rounded-full bg-blue-600" />
          <h1 className="text-xl font-bold">Auditing site in progress…</h1>
          <button
            className="ml-auto rounded border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
            disabled={cancelMutation.isPending}
            onClick={() => cancelMutation.mutate()}
          >
            {cancelMutation.isPending ? 'Cancelling…' : 'Cancel Audit'}
          </button>
        </div>

        <div className="mt-4">
          <div className="flex justify-between text-xs font-medium text-slate-600">
            <span>Phase: <strong className="uppercase text-blue-700">{run.phase || run.status}</strong></span>
            <span>Crawled: <strong>{crawled}</strong> / {discovered} discovered</span>
          </div>
          <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full bg-blue-600 transition-all duration-300 ease-out"
              style={{ width: `${Math.max(5, progressPct)}%` }}
            />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 text-center">
          <div className="rounded border bg-slate-50 p-2">
            <div className="text-[10px] uppercase text-slate-500">Speed</div>
            <div className="text-sm font-bold text-slate-800">{run.speed ? `${run.speed} p/s` : 'measuring…'}</div>
          </div>
          <div className="rounded border bg-slate-50 p-2">
            <div className="text-[10px] uppercase text-slate-500">ETA</div>
            <div className="text-sm font-bold text-slate-800">{run.eta_seconds ? `${Math.ceil(run.eta_seconds)}s` : '–'}</div>
          </div>
          <div className="rounded border bg-slate-50 p-2">
            <div className="text-[10px] uppercase text-slate-500">Discovered</div>
            <div className="text-sm font-bold text-slate-800">{discovered}</div>
          </div>
          <div className="rounded border bg-slate-50 p-2">
            <div className="text-[10px] uppercase text-slate-500">Failed / Errors</div>
            <div className="text-sm font-bold text-slate-800">{run.pages_failed || 0}</div>
          </div>
        </div>

        {run.error && <p className="mt-3 text-xs text-red-600">{run.error}</p>}
      </div>
    );
  }

  // Cancelled or Failed view without completed results
  if (run.status === 'FAILED' && !run.health_score) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
        <h2 className="text-lg font-bold text-red-800">Audit Failed</h2>
        <p className="mt-1 text-sm text-red-600">{run.error || 'The audit encountered an unrecoverable failure.'}</p>
        <Link className="mt-4 inline-block text-xs font-medium text-slate-900 underline" to="..">← Return to Audits</Link>
      </div>
    );
  }

  return (
    <div>
      <Link className="text-xs text-slate-500 hover:text-slate-800 underline" to="..">← All audits</Link>
      
      {/* Header Dashboard */}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Health {run.health_score ?? '–'}/100</h1>
          <p className="text-xs text-slate-500">
            {run.pages_crawled} pages crawled · {run.rules_firing || 0} rules firing · {run.issues_found || 0} affected URLs
            {run.status === 'CANCELLED' && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">Partial (Cancelled)</span>}
          </p>
        </div>
      </div>

      {/* Category Buckets */}
      {run.buckets && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(run.buckets).map(([b, v]) => (
            <div key={b} className="rounded-xl border bg-white p-3 shadow-xs">
              <div className="text-xs uppercase tracking-wider text-slate-500">{b}</div>
              <div className="text-xl font-bold text-slate-900">{v}</div>
              <div className="mt-1.5 h-1.5 rounded-full bg-slate-100">
                <div
                  className={`h-1.5 rounded-full ${v >= 80 ? 'bg-green-600' : v >= 60 ? 'bg-amber-500' : 'bg-red-600'}`}
                  style={{ width: `${v}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="mt-6 flex border-b border-slate-200">
        <button
          className={`border-b-2 px-4 py-2 text-sm font-medium ${
            activeTab === 'issues'
              ? 'border-slate-900 text-slate-900'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('issues')}
        >
          Issues ({run.rules_firing || 0})
        </button>
        <button
          className={`border-b-2 px-4 py-2 text-sm font-medium ${
            activeTab === 'pages'
              ? 'border-slate-900 text-slate-900'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('pages')}
        >
          Crawled Pages ({run.pages_crawled})
        </button>
      </div>

      {/* Tab Content: Issues */}
      {activeTab === 'issues' && (
        <div className="mt-4">
          <div className="flex flex-wrap gap-2 text-xs">
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1.5 text-slate-700"
              value={sev}
              onChange={e => { setSev(e.target.value); setPage(1); }}
            >
              <option value="">All severities</option>
              {['CRITICAL', 'ERROR', 'WARNING', 'NOTICE'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1.5 text-slate-700"
              value={cat}
              onChange={e => { setCat(e.target.value); setPage(1); }}
            >
              <option value="">All categories</option>
              {['Crawlability', 'Indexability', 'Metadata', 'Content', 'Links', 'Images', 'Canonical', 'Redirects', 'HTTPS', 'Structured Data', 'Performance', 'International'].map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div className="mt-3">
            <DataTable
              columns={[
                {
                  key: 'sev',
                  header: 'Severity',
                  render: r => (
                    <span className={`inline-flex rounded px-2 py-0.5 text-xs font-semibold ${
                      r.severity === 'CRITICAL' ? 'bg-red-700 text-white' :
                      r.severity === 'ERROR' ? 'bg-red-100 text-red-800' :
                      r.severity === 'WARNING' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-700'
                    }`}>
                      {r.severity}
                    </span>
                  ),
                  sortValue: r => SEV_ORDER[r.severity] ?? 9,
                },
                {
                  key: 'rule',
                  header: 'Rule',
                  render: r => (
                    <div>
                      <span className="font-mono text-xs text-slate-500">{r.rule_code}</span>
                      <div className="font-medium text-slate-900">{r.rule_name}</div>
                    </div>
                  )
                },
                {
                  key: 'msg',
                  header: 'Finding & Recommendation',
                  render: r => (
                    <div>
                      <div className="text-slate-800">{r.message}</div>
                      <div className="mt-0.5 text-xs text-slate-500">{r.recommendation}</div>
                    </div>
                  )
                },
                {
                  key: 'n',
                  header: 'Affected URLs',
                  render: r => <IssueUrls orgId={orgId} projectId={projectId} issue={r} />,
                  sortValue: r => r.affected_count,
                },
              ]}
              rows={issues?.items || []}
              total={issues?.total || 0}
              page={page}
              pageSize={20}
              onPage={setPage}
              search={search}
              onSearch={s => { setSearch(s); setPage(1); }}
              searchPlaceholder="Search issues…"
              onExportCsv={() => {
                const rows = (issues?.items || []).map(i => [i.severity, i.rule_code, i.rule_name, i.message, i.affected_count, i.recommendation]);
                downloadCsv(`audit-${rid}-issues.csv`, toCsv(['severity', 'rule', 'name', 'message', 'urls', 'recommendation'], rows));
              }}
              rowKey={r => r.id}
            />
          </div>
        </div>
      )}

      {/* Tab Content: Crawled Pages Table */}
      {activeTab === 'pages' && (
        <div className="mt-4">
          <div className="flex flex-wrap gap-2 text-xs">
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1.5 text-slate-700"
              value={pagesStatus || ''}
              onChange={e => { setPagesStatus(e.target.value ? Number(e.target.value) : undefined); setPagesPage(1); }}
            >
              <option value="">All status codes</option>
              <option value="200">200 OK</option>
              <option value="301">301 Redirect</option>
              <option value="302">302 Redirect</option>
              <option value="404">404 Not Found</option>
              <option value="500">500 Server Error</option>
            </select>
          </div>

          <div className="mt-3">
            <DataTable<CrawlPageRow>
              columns={[
                {
                  key: 'url',
                  header: 'URL',
                  render: r => (
                    <div className="max-w-xs truncate font-mono text-xs">
                      <a href={r.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline" title={r.url}>
                        {r.url}
                      </a>
                    </div>
                  ),
                },
                {
                  key: 'status',
                  header: 'Status',
                  render: r => <StatusBadge code={r.status_code} />,
                  sortValue: r => r.status_code ?? 0,
                },
                {
                  key: 'indexability',
                  header: 'Indexability',
                  render: r => <IndexabilityBadge status={r.indexability} />,
                },
                {
                  key: 'title',
                  header: 'Title Tag',
                  render: r => <div className="max-w-xs truncate text-xs" title={r.title || ''}>{r.title || <span className="text-slate-400 italic">None</span>}</div>,
                },
                {
                  key: 'h1',
                  header: 'H1',
                  render: r => <div className="max-w-xs truncate text-xs" title={r.h1 || ''}>{r.h1 || <span className="text-slate-400 italic">None</span>}</div>,
                },
                {
                  key: 'words',
                  header: 'Words',
                  render: r => <span className="text-xs text-slate-600">{r.word_count != null ? r.word_count : '–'}</span>,
                  sortValue: r => r.word_count ?? 0,
                },
                {
                  key: 'time',
                  header: 'Latency',
                  render: r => <span className="text-xs text-slate-500">{r.response_time_ms != null ? `${r.response_time_ms}ms` : '–'}</span>,
                  sortValue: r => r.response_time_ms ?? 0,
                },
              ]}
              rows={pagesData?.items || []}
              total={pagesData?.total || 0}
              page={pagesPage}
              pageSize={20}
              onPage={setPagesPage}
              search={pagesSearch}
              onSearch={s => { setPagesSearch(s); setPagesPage(1); }}
              searchPlaceholder="Filter crawled URLs or titles…"
              onExportCsv={() => {
                const rows = (pagesData?.items || []).map(p => [p.url, p.status_code, p.indexability, p.title, p.h1, p.word_count, p.response_time_ms]);
                downloadCsv(`audit-${rid}-pages.csv`, toCsv(['url', 'status_code', 'indexability', 'title', 'h1', 'words', 'latency_ms'], rows));
              }}
              rowKey={r => r.id}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function IssueUrls({ orgId, projectId, issue }: { orgId: string; projectId: string; issue: { id: string; affected_count: number } }) {
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ['issue-urls', issue.id], enabled: open,
    queryFn: () => seo.issueUrls(orgId, projectId, issue.id, 1, 20),
  });
  if (!open) return <button className="text-xs text-blue-600 underline" onClick={() => setOpen(true)}>{issue.affected_count} URLs</button>;
  return (
    <div className="max-w-md">
      <button className="text-xs text-slate-500 underline" onClick={() => setOpen(false)}>hide</button>
      <ul className="mt-1 max-h-40 list-disc overflow-auto pl-5 text-xs text-slate-700">
        {(data?.items || []).map(u => <li key={u.url} className="break-all"><a className="text-blue-600 underline" href={u.url} target="_blank" rel="noreferrer">{u.url}</a></li>)}
      </ul>
      {(data?.total || 0) > 20 && <p className="text-[10px] text-slate-400">showing 20 of {data?.total}</p>}
    </div>
  );
}
