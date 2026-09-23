import { api } from './api';

export type AuditRun = {
  id: string; project_id: string; status: string;
  started_at: string | null; finished_at: string | null;
  pages_discovered: number; pages_crawled: number; issues_found: number;
  health_score: number | null; error: string | null; created_at: string | null;
};

export type AuditDetail = AuditRun & {
  by_severity: Record<string, number>;
  buckets: Record<string, number>;
  rules_firing: number;
  job: { id: string; status: string; progress: number } | null;
};

export type Issue = {
  id: string; rule_code: string; rule_name: string; severity: string;
  category: string; message: string; why_it_matters: string;
  recommendation: string; status: string; affected_count: number;
};

export type Page<T> = { items: T[]; page: number; page_size: number; total: number };

export type Overview = {
  project: { id: string; name: string; domain: string; country: string; language: string; device: string };
  audit: null | {
    run_id: string; status: string; health_score: number | null;
    pages_crawled: number; pages_discovered: number; issues_found: number;
    finished_at: string | null; by_severity: Record<string, number>;
  };
  tracked_keywords: number;
  competitors: number;
  open_recommendations: number;
  top_opportunities: { id: string; title: string; score: number; severity: string; type: string }[];
  gsc_connected: boolean;
  latest_job: null | { id: string; job_type: string; status: string; progress: number };
};

export type KeywordRow = {
  id: string; keyword: string; country: string; language: string;
  intent: string | null; intent_confidence: number | null;
  search_volume: number | null; cpc: number | null; competition: number | null;
  trend: number[] | null; difficulty: number | null; difficulty_note: string | null;
  opportunity: number | null; serp_features: string[] | null; provider: string | null;
  updated_at: string | null;
};

export type SerpSummary = {
  id: string; keyword: string; engine: string; country: string; language: string;
  device: string; location: string | null; status: string; provider: string;
  searched_at: string | null; results: number; features: number;
};

export type TrackedRow = {
  id: string; keyword: string; country: string; language: string; device: string;
  engine: string; location: string | null; is_active: boolean;
  current_rank: number | null; current_url: string | null; previous_rank: number | null;
  change: number | null; best_rank: number | null; worst_rank: number | null;
  observations: number; last_checked_at: string | null;
};

export type ProviderMeta = {
  provider: string; label: string; kind: string[]; status?: string;
  fields: { name: string; label: string; secret: boolean }[]; docs: string;
};

export type ProviderAccount = {
  id: string; provider: string; label: string;
  credentials_masked: Record<string, string>; status: string;
  last_tested_at: string | null; last_error: string | null;
};

const base = (org: string, proj: string) => `/api/v1/organizations/${org}/projects/${proj}`;

export const seo = {
  overview: (org: string, proj: string) => api.get<Overview>(`${base(org, proj)}/overview`),
  startAudit: (org: string, proj: string, max_pages = 200) =>
    api.post<{ run: AuditRun; job: { id: string; status: string } }>(`${base(org, proj)}/audits`, { max_pages }),
  audits: (org: string, proj: string, page = 1, page_size = 20) =>
    api.get<Page<AuditRun>>(`${base(org, proj)}/audits?page=${page}&page_size=${page_size}`),
  audit: (org: string, proj: string, run: string) =>
    api.get<AuditDetail>(`${base(org, proj)}/audits/${run}`),
  issues: (org: string, proj: string, run: string, params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return api.get<Page<Issue>>(`${base(org, proj)}/audits/${run}/issues${q ? `?${q}` : ''}`);
  },
  issueUrls: (org: string, proj: string, issue: string, page = 1, page_size = 50) =>
    api.get<Page<{ url: string; detected_at: string }>>(`${base(org, proj)}/issues/${issue}/urls?page=${page}&page_size=${page_size}`),

  // providers (org scope)
  providerMeta: () => api.get<{ items: ProviderMeta[] }>('/api/v1/providers'),
  providerAccounts: (org: string) => api.get<{ items: ProviderAccount[] }>(`/api/v1/organizations/${org}/providers`),
  saveProvider: (org: string, provider: string, label: string, credentials: Record<string, string>) =>
    api.post<ProviderAccount>(`/api/v1/organizations/${org}/providers`, { provider, label, credentials }),
  deleteProvider: (org: string, id: string) => api.del(`/api/v1/organizations/${org}/providers/${id}`),
  testProvider: (org: string, id: string) =>
    api.post<{ ok: boolean; status: string; error?: string }>(`/api/v1/organizations/${org}/providers/${id}/test`),
  usage: (org: string) => api.get<{ items: { provider: string; service: string; operation: string; units: number; calls: number }[] }>(`/api/v1/organizations/${org}/usage`),
  limits: (org: string) =>
    api.get<{
      plan: string; limits: Record<string, number>;
      usage: { projects: number; monthly_serp: number; monthly_keywords: number; monthly_exports: number };
    }>(`/api/v1/organizations/${org}/limits`),

  // keywords
  research: (org: string, proj: string, seed: string, country = 'US', language = 'en', limit = 100) =>
    api.post<{ job: { id: string; status: string } }>(`${base(org, proj)}/keywords/research`, { seed, country, language, limit }),
  keywords: (org: string, proj: string, params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return api.get<Page<KeywordRow>>(`${base(org, proj)}/keywords${q ? `?${q}` : ''}`);
  },
  keyword: (org: string, proj: string, id: string) =>
    api.get<KeywordRow & { history: { search_volume: number | null; cpc: number | null; competition: number | null; difficulty: number | null; opportunity: number | null; provider: string | null; observed_at: string }[] }>(`${base(org, proj)}/keywords/${id}`),

  // serp
  serpSearch: (org: string, proj: string, body: { keyword: string; country?: string; language?: string; device?: string; depth?: number; force_refresh?: boolean }) =>
    api.post<{ job: { id: string; status: string } }>(`${base(org, proj)}/serp/search`, body),
  serpHistory: (org: string, proj: string, page = 1, page_size = 20) =>
    api.get<Page<SerpSummary>>(`${base(org, proj)}/serp?page=${page}&page_size=${page_size}`),
  serpDetail: (org: string, proj: string, id: string) =>
    api.get<SerpSummary & {
      result_items: { position: number; domain: string; url: string; title: string | null; snippet: string | null; result_type: string; feature_type: string | null }[];
      feature_items: { feature_type: string; position: number | null; data: Record<string, string> }[];
    }>(`${base(org, proj)}/serp/${id}`),

  // rank tracking
  trackKeyword: (org: string, proj: string, body: { keyword: string; country?: string; language?: string; device?: string; engine?: string }) =>
    api.post<TrackedRow>(`${base(org, proj)}/tracked-keywords`, body),
  tracked: (org: string, proj: string, page = 1, page_size = 100) =>
    api.get<Page<TrackedRow>>(`${base(org, proj)}/tracked-keywords?page=${page}&page_size=${page_size}`),
  untrack: (org: string, proj: string, id: string) => api.del(`${base(org, proj)}/tracked-keywords/${id}`),
  rankHistory: (org: string, proj: string, id: string, days = 90) =>
    api.get<{ items: { observed_at: string; rank: number | null; ranking_url: string | null; serp_features: string[] | null }[] }>(`${base(org, proj)}/tracked-keywords/${id}/history?days=${days}`),

  // competitors + gap
  gap: (org: string, proj: string, params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return api.get<{
      items: { keyword: string; your_rank: number | null; competitor_ranks: Record<string, number | null>; bucket: string; search_volume: number | null; difficulty: number | null; intent: string | null; opportunity: number | null }[];
      page: number; page_size: number; total: number;
      competitors: { id: string; domain: string }[];
    }>(`${base(org, proj)}/keyword-gap${q ? `?${q}` : ''}`);
  },
  gapCsv: async (org: string, proj: string) => {
    const { getBackendUrl } = await import('./api');
    const token = localStorage.getItem('seo.token');
    const res = await fetch(`${getBackendUrl()}${base(org, proj)}/keyword-gap/export`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Export failed (${res.status})`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'keyword-gap.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  },

  // search console
  gscAuthUrl: (org: string, proj: string) =>
    api.get<{ auth_url: string }>(`${base(org, proj)}/gsc/auth-url`),
  gscConnections: (org: string, proj: string) =>
    api.get<{ items: { id: string; google_account: string | null; status: string; expires_at: string | null; properties: { id: string; site_url: string; property_type: string; project_id: string | null; is_selected: boolean; last_synced_at: string | null }[] }[] }>(`${base(org, proj)}/gsc/connections`),
  gscSelect: (org: string, proj: string, property_id: string) =>
    api.post(`${base(org, proj)}/gsc/select`, { property_id }),
  gscSync: (org: string, proj: string, property_id?: string, days = 90) =>
    api.post<{ job: { id: string; status: string }; property_id: string }>(`${base(org, proj)}/gsc/sync`, { property_id, days }),
  gscOverview: (org: string, proj: string, days = 28) =>
    api.get<{
      property: { id: string; site_url: string; last_synced_at: string | null };
      queries: { clicks: number; impressions: number; ctr: number; avg_position: number };
      pages: { clicks: number; impressions: number; ctr: number; avg_position: number };
      daily: { date: string; clicks: number; impressions: number }[];
    }>(`${base(org, proj)}/gsc/overview?days=${days}`),
  gscQueries: (org: string, proj: string, params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return api.get<Page<{ query: string; clicks: number; impressions: number; ctr: number; position: number }>>(`${base(org, proj)}/gsc/queries${q ? `?${q}` : ''}`);
  },
  gscPages: (org: string, proj: string, params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return api.get<Page<{ page: string; clicks: number; impressions: number; ctr: number; position: number }>>(`${base(org, proj)}/gsc/pages${q ? `?${q}` : ''}`);
  },
  gscDisconnect: (org: string, proj: string, id: string) => api.del(`${base(org, proj)}/gsc/connections/${id}`),

  // recommendations
  recommendations: (org: string, proj: string, params: Record<string, string | number> = {}) => {
    const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
    return api.get<Page<{
      id: string; type: string; source: string; severity: string; impact: number;
      effort: number; confidence: number; score: number; title: string;
      description: string; why: string; recommended_action: string;
      related_url: string | null; related_keyword: string | null; status: string;
    }> & { by_status: Record<string, number> }>(`${base(org, proj)}/recommendations${q ? `?${q}` : ''}`);
  },
  recoStatus: (id: string, status: string) =>
    api.patch(`/api/v1/recommendations/${id}`, { status }),
  recalculate: (org: string, proj: string) =>
    api.post<{ job: { id: string; status: string } }>(`${base(org, proj)}/recommendations/recalculate`),

  // reports
  createReport: (org: string, proj: string, type: string, format: string) =>
    api.post<{ report: { id: string; type: string; status: string }; export: { id: string; format: string; status: string }; job: { id: string; status: string } }>(`${base(org, proj)}/reports`, { type, format }),
  reports: (org: string, proj: string, page = 1, page_size = 20) =>
    api.get<Page<{
      id: string; type: string; status: string; error: string | null; created_at: string | null;
      exports: { id: string; format: string; status: string; expires_at: string | null }[];
    }>>(`${base(org, proj)}/reports?page=${page}&page_size=${page_size}`),
  reportDownload: async (org: string, proj: string, exportId: string, filename: string) => {
    const { getBackendUrl } = await import('./api');
    const token = localStorage.getItem('seo.token');
    const res = await fetch(`${getBackendUrl()}${base(org, proj)}/reports/exports/${exportId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};
