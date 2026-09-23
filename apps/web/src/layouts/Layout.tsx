import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth';

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="flex min-h-screen">
      <aside className="w-60 shrink-0 border-r bg-white p-4">
        <div className="text-lg font-bold">SEO Intelligence</div>
        <nav className="mt-6 space-y-1 text-sm">
          <Link className="block rounded px-3 py-2 hover:bg-slate-100" to="/dashboard">Dashboard</Link>
          <Link className="block rounded px-3 py-2 hover:bg-slate-100" to="/projects">Projects</Link>
          <Link className="block rounded px-3 py-2 hover:bg-slate-100" to="/settings/providers">Settings</Link>
        </nav>
        <div className="mt-8 text-xs text-slate-500">
          {user ? (
            <>
              <div className="truncate">{user.email}</div>
              <button className="mt-2 underline" onClick={() => { logout(); nav('/login'); }}>Logout</button>
            </>
          ) : <Link className="underline" to="/login">Login</Link>}
        </div>
      </aside>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
