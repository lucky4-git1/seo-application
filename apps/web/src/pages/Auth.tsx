import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  return (
    <div className="mx-auto mt-24 max-w-sm rounded-xl border bg-white p-6">
      <h1 className="text-xl font-bold">Login</h1>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <input className="mt-4 w-full rounded border px-3 py-2" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
      <input className="mt-2 w-full rounded border px-3 py-2" placeholder="Password" type="password" value={password} onChange={e => setPassword(e.target.value)} />
      <button className="mt-4 w-full rounded bg-slate-900 px-3 py-2 text-white" onClick={() => login(email, password).then(() => nav('/dashboard')).catch((e: Error) => setErr(e.message))}>Login</button>
      <p className="mt-3 text-sm">No account? <Link className="underline" to="/register">Register</Link></p>
    </div>
  );
}

export function RegisterPage() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  return (
    <div className="mx-auto mt-24 max-w-sm rounded-xl border bg-white p-6">
      <h1 className="text-xl font-bold">Register</h1>
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      <input className="mt-4 w-full rounded border px-3 py-2" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
      <input className="mt-2 w-full rounded border px-3 py-2" placeholder="Password (8+ chars)" type="password" value={password} onChange={e => setPassword(e.target.value)} />
      <button className="mt-4 w-full rounded bg-slate-900 px-3 py-2 text-white" onClick={() => register(email, password).then(() => nav('/dashboard')).catch((e: Error) => setErr(e.message))}>Create account</button>
    </div>
  );
}
