import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { EmptyState, ErrorState, Skeleton } from '../components/states';

type Org = { id: string; name: string; slug: string; plan: string };
type Project = { id: string; organization_id: string; name: string; domain: string; country: string; language: string; device: string; is_archived: boolean };

export function DashboardPage() {
  const { data: orgs, isLoading, error } = useQuery({ queryKey: ['orgs'], queryFn: () => api.get<Org[]>('/api/v1/organizations') });
  if (isLoading) return <Skeleton className="h-40" />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!orgs?.length) return <EmptyState title="No organizations yet" hint="Create an organization to group your SEO projects." action={<Link className="rounded bg-slate-900 px-4 py-2 text-white" to="/projects">Get started</Link>} />;
  return (
    <div>
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <p className="text-sm text-slate-500">DATA → ANALYSIS → OPPORTUNITY → ACTION. Select a project to see what to do next.</p>
      <div className="mt-4 grid gap-3">
        {orgs.map(o => <OrgCard key={o.id} org={o} />)}
      </div>
    </div>
  );
}

function OrgCard({ org }: { org: Org }) {
  const { data } = useQuery({ queryKey: ['projects', org.id], queryFn: () => api.get<{ items: Project[] }>(`/api/v1/organizations/${org.id}/projects`) });
  return (
    <div className="rounded-xl border bg-white p-4">
      <div className="font-semibold">{org.name} <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs">{org.plan}</span></div>
      {!data?.items.length
        ? <p className="mt-2 text-sm text-slate-500">No projects yet. Create one to start analysis.</p>
        : <ul className="mt-2 text-sm">{data.items.map(p => <li key={p.id}><Link className="underline" to={`/projects/${org.id}/${p.id}`}>{p.name}</Link> <span className="text-slate-400">· {p.domain}</span></li>)}</ul>}
    </div>
  );
}

export function ProjectsPage() {
  const qc = useQueryClient();
  const { data: orgs } = useQuery({ queryKey: ['orgs'], queryFn: () => api.get<Org[]>('/api/v1/organizations') });
  const [orgId, setOrgId] = useState('');
  const [name, setName] = useState('');
  const [domain, setDomain] = useState('');
  const [err, setErr] = useState('');
  const activeOrg = orgId || orgs?.[0]?.id || '';
  const { data: projs, isLoading } = useQuery({
    queryKey: ['projects', activeOrg], enabled: !!activeOrg,
    queryFn: () => api.get<{ items: Project[] }>(`/api/v1/organizations/${activeOrg}/projects`),
  });
  const createOrg = useMutation({
    mutationFn: (n: string) => api.post<Org>('/api/v1/organizations', { name: n }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orgs'] }),
  });
  const createProject = async () => {
    setErr('');
    try {
      await api.post(`/api/v1/organizations/${activeOrg}/projects`, { name, domain, country: 'US', language: 'en', device: 'DESKTOP', competitors: [] });
      setName(''); setDomain('');
      qc.invalidateQueries({ queryKey: ['projects', activeOrg] });
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div>
      <h1 className="text-2xl font-bold">Projects</h1>
      <div className="mt-4 flex gap-2">
        <select className="rounded border px-2 py-1" value={activeOrg} onChange={e => setOrgId(e.target.value)}>
          {(orgs || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <button className="rounded border px-3 py-1" onClick={() => { const n = prompt('Organization name:'); if (n) createOrg.mutate(n); }}>+ Org</button>
      </div>
      {isLoading ? <Skeleton className="mt-4 h-24" /> : !projs?.items.length
        ? <div className="mt-4"><EmptyState title="No projects yet" hint="Add your website to begin monitoring search visibility." /></div>
        : <ul className="mt-4 space-y-2">{projs.items.map(p => <li key={p.id} className="rounded border bg-white p-3"><Link className="font-medium underline" to={`/projects/${activeOrg}/${p.id}`}>{p.name}</Link><span className="ml-2 text-sm text-slate-500">{p.domain} · {p.country}/{p.language}/{p.device}</span></li>)}</ul>}
      <div className="mt-6 max-w-md rounded-xl border bg-white p-4">
        <h2 className="font-semibold">New project</h2>
        {err && <p className="text-sm text-red-600">{err}</p>}
        <input className="mt-2 w-full rounded border px-3 py-2" placeholder="Project name" value={name} onChange={e => setName(e.target.value)} />
        <input className="mt-2 w-full rounded border px-3 py-2" placeholder="example.com" value={domain} onChange={e => setDomain(e.target.value)} />
        <button className="mt-2 rounded bg-slate-900 px-4 py-2 text-white" onClick={createProject}>Create</button>
      </div>
    </div>
  );
}

export function SettingsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Settings</h1>
      <div className="mt-4"><EmptyState title="No providers configured" hint="SERP data unavailable — connect a SERP provider to perform analysis." /></div>
    </div>
  );
}
