import { NavLink, Outlet, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: '', label: 'Overview', end: true },
  { to: 'keywords', label: 'Keyword Research' },
  { to: 'serp', label: 'SERP Analysis' },
  { to: 'rankings', label: 'Position Tracking' },
  { to: 'competitors', label: 'Competitors' },
  { to: 'keyword-gap', label: 'Keyword Gap' },
  { to: 'gsc', label: 'Search Console' },
  { to: 'recommendations', label: 'Recommendations' },
  { to: 'reports', label: 'Reports' },
  { to: 'audit', label: 'Site Audit' },
];

export function ProjectLayout() {
  const { orgId, projectId } = useParams();
  const { data: project } = useQuery({
    queryKey: ['project', orgId, projectId], enabled: !!orgId && !!projectId,
    queryFn: () => api.get<{ name: string; domain: string; country: string; language: string; device: string }>(
      `/api/v1/organizations/${orgId}/projects/${projectId}`),
  });
  const base = `/projects/${orgId}/${projectId}`;
  return (
    <div className="flex min-h-[calc(100vh-0px)] gap-6">
      <aside className="w-52 shrink-0">
        <div className="rounded-xl border bg-white p-3">
          <div className="truncate text-sm font-bold">{project?.name || '…'}</div>
          <div className="truncate text-xs text-slate-500">{project?.domain || ''}</div>
          {project && <div className="mt-1 text-[11px] text-slate-400">{project.country} · {project.language} · {project.device}</div>}
        </div>
        <nav className="mt-3 space-y-1 text-sm">
          {NAV.map(n => (
            <NavLink key={n.to} to={`${base}${n.to ? `/${n.to}` : ''}`} end={n.end}
              className={({ isActive }) => `block rounded px-3 py-2 ${isActive ? 'bg-slate-900 text-white' : 'hover:bg-slate-100'}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0 flex-1"><Outlet /></div>
    </div>
  );
}
