import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { EmptyState, ErrorState, Skeleton } from '../components/states';
import { getBackendUrl, setBackendUrl } from '../lib/api';
import { seo, type ProviderAccount } from '../lib/seo';

function StatusDot({ status }: { status: string }) {
  const c = status === 'ACTIVE' ? 'bg-green-500' : status === 'INVALID' ? 'bg-red-500' : status === 'ERROR' ? 'bg-amber-500' : 'bg-slate-300';
  return <span className={`inline-block h-2 w-2 rounded-full ${c}`} title={status} />;
}

export function ProvidersPage() {
  const qc = useQueryClient();
  // org scope: pick org from URL? settings page is global — use first org with a select.
  const { data: orgs } = useQuery({ queryKey: ['orgs'], queryFn: () => import('../lib/api').then(m => m.api.get<{ id: string; name: string }[]>('/api/v1/organizations')) });
  const [orgId, setOrgId] = useState('');
  const activeOrg = orgId || orgs?.[0]?.id || '';
  const { data: meta } = useQuery({ queryKey: ['provider-meta'], queryFn: () => seo.providerMeta() });
  const { data: accounts, isLoading, error } = useQuery({
    queryKey: ['providers', activeOrg], enabled: !!activeOrg,
    queryFn: () => seo.providerAccounts(activeOrg),
  });
  const { data: usage } = useQuery({
    queryKey: ['usage', activeOrg], enabled: !!activeOrg,
    queryFn: () => seo.usage(activeOrg),
  });
  const { data: limits } = useQuery({
    queryKey: ['limits', activeOrg], enabled: !!activeOrg,
    queryFn: () => seo.limits(activeOrg),
  });
  const [backendUrl, setBackendUrlInput] = useState(getBackendUrl());
  const [backendMsg, setBackendMsg] = useState('');
  const testBackend = async () => {
    setBackendMsg('Testing…');
    try {
      const res = await fetch(`${backendUrl.replace(/\/$/, '')}/api/v1/health`);
      setBackendMsg(res.ok ? 'Connected.' : `Failed (${res.status}).`);
    } catch {
      setBackendMsg('Failed to reach backend.');
    }
  };
  const [editing, setEditing] = useState<string | null>(null);
  const [label, setLabel] = useState('default');
  const [fields, setFields] = useState<Record<string, string>>({});
  const [formErr, setFormErr] = useState('');
  const [testing, setTesting] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => seo.saveProvider(activeOrg, editing!, label, fields),
    onSuccess: () => { setEditing(null); setFields({}); setLabel('default'); setFormErr(''); qc.invalidateQueries({ queryKey: ['providers', activeOrg] }); },
    onError: (e) => setFormErr((e as Error).message),
  });
  const del = useMutation({
    mutationFn: (id: string) => seo.deleteProvider(activeOrg, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers', activeOrg] }),
  });
  const test = async (a: ProviderAccount) => {
    setTesting(a.id);
    try {
      const r = await seo.testProvider(activeOrg, a.id);
      if (!r.ok) alert(`Connection failed: ${r.error || r.status}`);
    } catch (e) { alert(`Connection failed: ${(e as Error).message}`); }
    setTesting(null);
    qc.invalidateQueries({ queryKey: ['providers', activeOrg] });
  };

  const byProvider: Record<string, ProviderAccount[]> = {};
  (accounts?.items || []).forEach(a => { (byProvider[a.provider] = byProvider[a.provider] || []).push(a); });

  return (
    <div>
      <h1 className="text-2xl font-bold">Provider settings</h1>
      <p className="text-sm text-slate-500">Connect SEO data providers. Secrets are encrypted at rest and never shown in full.</p>
      <div className="mt-3">
        <select className="rounded border px-2 py-1 text-sm" value={activeOrg} onChange={e => setOrgId(e.target.value)}>
          {(orgs || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </div>
      {isLoading ? <Skeleton className="mt-4 h-40" />
        : error ? <ErrorState message={(error as Error).message} />
        : <div className="mt-4 grid gap-3">
          {(meta?.items || []).map(m => (
            <div key={m.provider} className="rounded-xl border bg-white p-4">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{m.label}</span>
                <span className="text-xs text-slate-400">{m.kind.join(' + ')}</span>
                <span className="ml-auto flex gap-1">{(byProvider[m.provider] || []).map(a => <StatusDot key={a.id} status={a.status} />)}</span>
              </div>
              {m.status === 'planned' && <p className="mt-1 text-xs text-amber-700">Integration planned — account form disabled until the provider client ships.</p>}
              {(byProvider[m.provider] || []).map(a => (
                <div key={a.id} className="mt-2 flex flex-wrap items-center gap-2 rounded border border-slate-100 p-2 text-sm">
                  <span className="font-medium">{a.label}</span>
                  <span className="text-xs text-slate-500">{Object.entries(a.credentials_masked).map(([k, v]) => `${k}: ${v}`).join(' · ')}</span>
                  <StatusDot status={a.status} /><span className="text-xs">{a.status}</span>
                  {a.last_error && <span className="text-xs text-red-600">{a.last_error}</span>}
                  <span className="ml-auto flex gap-2">
                    <button className="underline disabled:opacity-40" disabled={testing === a.id} onClick={() => test(a)}>{testing === a.id ? 'Testing…' : 'Test'}</button>
                    <button className="underline" onClick={() => { setEditing(m.provider); setLabel(a.label); setFields({}); }}>Edit</button>
                    <button className="underline text-red-600" onClick={() => { if (confirm('Disconnect this provider account?')) del.mutate(a.id); }}>Disconnect</button>
                  </span>
                </div>
              ))}
              {editing === m.provider && m.status !== 'planned' ? (
                <div className="mt-2 rounded border p-3 text-sm">
                  {formErr && <p className="text-red-600">{formErr}</p>}
                  <label className="block">Label <input className="mt-1 w-full rounded border px-2 py-1" value={label} onChange={e => setLabel(e.target.value)} /></label>
                  {m.fields.map(f => (
                    <label key={f.name} className="mt-2 block">{f.label}
                      <input className="mt-1 w-full rounded border px-2 py-1" type={f.secret ? 'password' : 'text'}
                        value={fields[f.name] || ''} onChange={e => setFields({ ...fields, [f.name]: e.target.value })} placeholder={f.secret ? '••••••' : ''} />
                    </label>
                  ))}
                  <div className="mt-2 flex gap-2">
                    <button className="rounded bg-slate-900 px-3 py-1.5 text-white" onClick={() => save.mutate()}>Save</button>
                    <button className="rounded border px-3 py-1.5" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">Saving replaces stored credentials. Secrets are encrypted before storage.</p>
                </div>
              ) : (m.status !== 'planned' && !(byProvider[m.provider] || []).length && (
                <button className="mt-2 rounded border px-3 py-1.5 text-sm" onClick={() => { setEditing(m.provider); setLabel('default'); setFields({}); }}>+ Connect {m.label}</button>
              ))}
            </div>
          ))}
          {!(meta?.items || []).length && <EmptyState title="No providers available" hint="No provider integrations are registered in this build." />}
        </div>}
      <div className="mt-6">
        <h2 className="font-semibold">Plan &amp; limits</h2>
        {!limits ? <p className="mt-1 text-sm text-slate-500">Loading…</p>
          : <div className="mt-2 max-w-2xl">
            <p className="text-sm">Plan: <b>{limits.plan}</b></p>
            {([['projects', 'Projects'], ['monthly_serp', 'SERP requests / mo'], ['monthly_keywords', 'Keyword requests / mo'], ['monthly_exports', 'Exports / mo']] as const).map(([k, label]) => {
              const used = (limits.usage as Record<string, number>)[k] ?? 0;
              const max = limits.limits[k === 'projects' ? 'projects' : k] ?? 0;
              const pct = max ? Math.min(100, (used / max) * 100) : 0;
              return (
                <div key={k} className="mt-1 text-sm">
                  <div className="flex justify-between"><span>{label}</span><span>{used} / {max}</span></div>
                  <div className="h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-slate-900" style={{ width: `${pct}%` }} /></div>
                </div>
              );
            })}
          </div>}
      </div>
      <div className="mt-6 max-w-2xl">
        <h2 className="font-semibold">Application / Backend URL</h2>
        <p className="mt-1 text-sm text-slate-500">The desktop app and this page use this URL to reach the API. Change it for self-hosted backends.</p>
        <div className="mt-2 flex gap-2">
          <input className="flex-1 rounded border px-3 py-1.5 text-sm" value={backendUrl} onChange={e => setBackendUrlInput(e.target.value)} />
          <button className="rounded border px-3 py-1.5 text-sm" onClick={testBackend}>Test</button>
          <button className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white" onClick={() => { setBackendUrl(backendUrl); setBackendMsg('Saved.'); }}>Save</button>
        </div>
        {backendMsg && <p className="mt-1 text-sm text-slate-600">{backendMsg}</p>}
      </div>
      <div className="mt-6">
        <h2 className="font-semibold">Usage (30 days)</h2>
        {!(usage?.items || []).length
          ? <p className="mt-1 text-sm text-slate-500">No provider usage recorded yet.</p>
          : <table className="mt-2 w-full max-w-2xl text-left text-sm">
            <thead><tr className="border-b text-xs uppercase text-slate-500"><th className="py-1">Provider</th><th>Service</th><th>Operation</th><th>Units</th><th>Calls</th></tr></thead>
            <tbody>{usage!.items.map((u, i) => <tr key={i} className="border-b"><td>{u.provider}</td><td>{u.service}</td><td>{u.operation}</td><td>{u.units}</td><td>{u.calls}</td></tr>)}</tbody>
          </table>}
      </div>
    </div>
  );
}
