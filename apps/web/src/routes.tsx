import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { Layout } from './layouts/Layout';
import { ProjectLayout } from './layouts/ProjectLayout';
import { LoginPage, RegisterPage } from './pages/Auth';
import { DashboardPage, ProjectsPage } from './pages/Projects';
import { ProvidersPage } from './pages/Providers';
import { ProjectOverviewPage } from './pages/ProjectOverview';
import { AuditDetailPage, AuditListPage } from './pages/Audit';
import { KeywordDetailPage, KeywordsPage } from './pages/Keywords';
import { CompetitorsPage, KeywordGapPage } from './pages/Competitors';
import { GscPage } from './pages/Gsc';
import { RecommendationsPage } from './pages/Recommendations';
import { ReportsPage } from './pages/Reports';
import { SerpDetailPage, SerpPage } from './pages/Serp';
import { RankingsPage } from './pages/Rankings';
import { useAuth } from './lib/auth';

function Guard({ children }: { children: JSX.Element }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function ProjectGuard() {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return <Layout><ProjectLayout /></Layout>;
}

export function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/dashboard" element={<Guard><DashboardPage /></Guard>} />
        <Route path="/projects" element={<Guard><ProjectsPage /></Guard>} />
        <Route path="/projects/:orgId/:projectId" element={<ProjectGuard />}>
          <Route index element={<ProjectOverviewPage />} />
          <Route path="keywords" element={<KeywordsPage />} />
          <Route path="keywords/:keywordId" element={<KeywordDetailPage />} />
          <Route path="serp" element={<SerpPage />} />
          <Route path="serp/:searchId" element={<SerpDetailPage />} />
          <Route path="rankings" element={<RankingsPage />} />
          <Route path="competitors" element={<CompetitorsPage />} />
          <Route path="keyword-gap" element={<KeywordGapPage />} />
          <Route path="gsc" element={<GscPage />} />
          <Route path="recommendations" element={<RecommendationsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="audit" element={<AuditListPage />} />
          <Route path="audit/:runId" element={<AuditDetailPage />} />
        </Route>
        <Route path="/settings/providers" element={<Guard><ProvidersPage /></Guard>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export function useProjectParams() {
  const { orgId, projectId } = useParams();
  return { orgId: orgId!, projectId: projectId! };
}
