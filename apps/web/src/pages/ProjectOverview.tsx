import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { seo } from '../lib/seo';
import { useProjectParams } from '../routes';

function SevBadge({ sev }: { sev: string }) {
  const colors: Record<string, string> = {
    CRITICAL: 'bg-red-700 text-white', ERROR: 'bg-red-100 text-red-800',
    WARNING: 'bg-amber-100 text-amber-800', NOTICE: 'bg-slate-100 text-slate-600',
  };
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${colors[sev] || 'bg-slate-100'}`}>{sev}</span>;
}

export function ProjectOverviewPage() {
  const { orgId, projectId } = useProjectParams();
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['overview', orgId, projectId],
    queryFn: () => seo.overview(orgId, projectId),
    refetchInterval: running ? 3000 : false,
  });
  const startAudit = useMutation({
    mutationFn: () => seo.startAudit(orgId, projectId, 200),
    onSuccess: () => { setRunning(true); refetch(); },
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !data) return <ErrorState message={(error as Error)?.message || 'Failed to load overview'} />;
  const { project, audit } = data;
  const active = audit && (audit.status === 'PENDING' || audit.status === 'RUNNING');
  const done = audit && audit.status === 'COMPLETED';

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-bold">{project.name}</h1>
          <p className="text-sm text-slate-500">{project.domain} · {project.country} · {project.language} · {project.device}</p>
        </div>
        <div className="ml-auto">
          {active
            ? <span className="rounded bg-blue-100 px-4 py-2 text-sm text-blue-800">Audit {audit.status.toLowerCase()}…</span>
            : <button className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
                disabled={startAudit.isPending}
                onClick={() => startAudit.mutate()}>
                {startAudit.isPending ? 'Starting…' : audit ? 'Re-run Audit' : 'Run Audit'}
              </button>}
        </div>
      </div>
      {startAudit.isError && <p className="mt-2 text-sm text-red-600">{(startAudit.error as Error).message}</p>}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border bg-white p-4">
          <div className="text-xs uppercase text-slate-500">SEO Health</div>
          <div className="mt-1 text-3xl font-bold">{done && audit.health_score != null ? `${audit.health_score}/100` : '–'}</div>
          {!audit && <p className="mt-1 text-xs text-slate-400">No audit yet</p>}
        </div>
        <div className="rounded-xl border bg-white p-4">
          <div className="text-xs uppercase text-slate-500">Tracked Keywords</div>
          <div className="mt-1 text-3xl font-bold">{data.tracked_keywords || '–'}</div>
          {!data.tracked_keywords && <p className="mt-1 text-xs text-slate-400">None tracked yet</p>}
        </div>
        <div className="rounded-xl border bg-white p-4">
          <div className="text-xs uppercase text-slate-500">Audit Issues</div>
          <div className="mt-1 text-3xl font-bold">{done ? audit.issues_found : '–'}</div>
          {!audit && <p className="mt-1 text-xs text-slate-400">Run an audit</p>}
        </div>
        <div className="rounded-xl border bg-white p-4">
          <div className="text-xs uppercase text-slate-500">Open Opportunities</div>
          <div className="mt-1 text-3xl font-bold">{data.open_recommendations || '–'}</div>
          {!data.open_recommendations && <p className="mt-1 text-xs text-slate-400">None yet</p>}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border bg-white p-4">
          <h2 className="font-semibold">Technical SEO</h2>
          {!audit ? <div className="mt-2"><EmptyState title="No site audit yet" hint="Run your first technical SEO audit." /></div>
            : active ? <p className="mt-2 text-sm text-slate-500">Crawling… {audit.pages_crawled} of {Math.max(audit.pages_discovered, audit.pages_crawled)} pages.</p>
            : <div className="mt-2 flex flex-wrap gap-2 text-sm">
                {Object.entries(audit.by_severity).map(([s, n]) => (
                  <span key={s} className="flex items-center gap-1"><SevBadge sev={s} /> {n}</span>
                ))}
                <Link className="ml-auto underline" to="audit">View audit →</Link>
              </div>}
        </div>
        <div className="rounded-xl border bg-white p-4">
          <h2 className="font-semibold">Top opportunities</h2>
          {!data.top_opportunities.length
            ? <p className="mt-2 text-sm text-slate-500">Recommendations appear here once audits, keywords and rankings produce data.</p>
            : <ul className="mt-2 space-y-1 text-sm">{data.top_opportunities.map(o => (
              <li key={o.id} className="flex items-center gap-2"><SevBadge sev={o.severity} /><span className="truncate">{o.title}</span><span className="ml-auto text-slate-400">{o.score.toFixed(0)}</span></li>))}</ul>}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <div className="rounded-xl border bg-white p-4 text-sm">
          <h2 className="font-semibold">Competitors</h2>
          <p className="mt-1 text-slate-500">{data.competitors ? `${data.competitors} tracked` : 'No competitors added yet.'}</p>
        </div>
        <div className="rounded-xl border bg-white p-4 text-sm">
          <h2 className="font-semibold">Search Console</h2>
          <p className="mt-1 text-slate-500">{data.gsc_connected ? 'Connected.' : 'Not connected.'}</p>
        </div>
        <div className="rounded-xl border bg-white p-4 text-sm">
          <h2 className="font-semibold">Crawl</h2>
          <p className="mt-1 text-slate-500">{audit ? `${audit.pages_crawled} pages in latest audit.` : 'Nothing crawled yet.'}</p>
        </div>
      </div>
    </div>
  );
}
