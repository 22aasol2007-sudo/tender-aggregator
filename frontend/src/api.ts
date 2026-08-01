const API = `${(import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || ""}/api`;

export type User = {
  id: number;
  email: string;
  name: string;
  is_admin: boolean;
  telegram_chat_id: string | null;
};

export type Tender = {
  id: number;
  external_id: string;
  source: string;
  law: string | null;
  title: string;
  customer: string | null;
  customer_inn: string | null;
  region: string | null;
  price: number | null;
  currency: string;
  status: string | null;
  status_norm: string;
  method: string | null;
  okpd2: string | null;
  url: string;
  description: string | null;
  documents: { name: string; url?: string | null }[] | null;
  lots: { name: string; price?: number | null; okpd2?: string | null }[] | null;
  is_duplicate: boolean;
  published_at: string | null;
  deadline_at: string | null;
  changed_at: string | null;
  relevance: number | null;
  watch_status: string | null;
};

export type TenderListResponse = {
  items: Tender[];
  total: number;
  page: number;
  page_size: number;
};

export type Stats = {
  total: number;
  active: number;
  by_source: Record<string, number>;
  by_law: Record<string, number>;
  last_scrape: string | null;
  database: string;
};

export type Dashboard = {
  total: number;
  active: number;
  avg_price: number | null;
  new_day: number;
  new_week: number;
  changed_day: number;
  top_regions: { region: string; count: number }[];
  by_source: Record<string, number>;
  series: { date: string; count: number }[];
  last_scrape: string | null;
};

export type SourceInfo = { id: string; name: string };
export type FilterPreset = {
  id: number;
  name: string;
  description: string | null;
  filters: Record<string, unknown>;
  is_builtin: boolean;
  is_shared?: boolean;
};

export type SavedSearch = {
  id: number;
  name: string;
  filters: Record<string, unknown>;
  new_count: number;
  notify_telegram: boolean;
};

export type Watch = {
  id: number;
  tender_id: number;
  status: string;
  notes: string | null;
  tags: string[];
  tender: Tender | null;
};

export type Profile = {
  company_name: string | null;
  okpd_prefixes: string[];
  regions: string[];
  keywords: string[];
  min_price: number | null;
  max_price: number | null;
};

export type TenderChange = {
  id: number;
  field: string;
  old_value: string | null;
  new_value: string | null;
  changed_at: string;
};

export type Filters = {
  q: string;
  exclude: string;
  match_any: boolean;
  source: string;
  law: string;
  region: string;
  method: string;
  okpd2: string;
  status_norm: string;
  min_price: string;
  max_price: string;
  deadline_from: string;
  deadline_to: string;
  hide_outdated: boolean;
  hide_duplicates: boolean;
  sort: string;
};

/** Keep in sync with backend/app/services/niche.py TRANSPORT_* (comma = phrase OR terms). */
export const TRANSPORT_DEFAULT_Q =
  "рефрижератор, рефтранспорт, хладотранспорт, изотерм, температурный режим, температурн, скоропортящ, холодовая цепь, холодная цепь, охлаждённ, охлажденн, замороженн, рефрижераторн, reefer, грузоперевоз, перевозка грузов, перевозки грузов, перевозку грузов, автоперевоз, доставка грузов, доставке грузов, транспортные услуги, транспортных услуг, транспортно-экспедиц, экспедирован, экспедиторск, фрахт, логистическ, логистик, автотранспортн, грузовым автомобил, автомобильным транспортом, перевозка продукции, перевозки продукции, перевозка товаров, перевозки товаров, услуги по перевозке, оказание услуг по перевозке, контейнерные перевоз, контейнерных перевоз, тентованн, негабаритн, сборных грузов, сборный груз, 49.41, 49.4, 52.29";

export const TRANSPORT_DEFAULT_EXCLUDE =
  "программное обеспечение, разработка сайта, лицензия ПО, антивирус, серверное оборудование, оргтехника, канцеляр, офисная мебель, уборка помещений, охранные услуги";

export const emptyFilters: Filters = {
  q: TRANSPORT_DEFAULT_Q,
  exclude: TRANSPORT_DEFAULT_EXCLUDE,
  match_any: true,
  source: "",
  law: "",
  region: "",
  method: "",
  okpd2: "",
  // Empty = all statuses (optional filters must not restrict by default)
  status_norm: "",
  min_price: "",
  max_price: "",
  deadline_from: "",
  deadline_to: "",
  hide_outdated: true,
  hide_duplicates: true,
  sort: "relevance",
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem("token");
}

export function isAuthFailure(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function clearToken() {
  localStorage.removeItem("token");
}

/** Only clear session on definitive auth failures for session endpoints — never on public 401s or login mistakes. */
function shouldClearTokenOn401(path: string): boolean {
  const bare = path.split("?")[0];
  return bare === "/auth/me" || bare === "/profile" || bare.startsWith("/watches") || bare.startsWith("/saved-searches");
}

/** Treat blank / placeholder strings as unset so they are omitted from the query. */
function optParam(value: string | null | undefined): string | null {
  if (value == null) return null;
  const s = String(value).trim();
  if (!s || s === "undefined" || s === "null" || s === "None") return null;
  return s;
}

function formatApiError(text: string, status: number): string {
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  } catch {
    /* not JSON */
  }
  return text.trim() || `HTTP ${status}`;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const maxAttempts = 3;
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(`${API}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(),
          ...(init?.headers || {}),
        },
        signal: init?.signal,
      });
      if (!res.ok) {
        if (res.status === 401 && shouldClearTokenOn401(path)) clearToken();
        const retryable = res.status === 429 || res.status === 502 || res.status === 503 || res.status === 504;
        if (retryable && attempt < maxAttempts && !init?.signal?.aborted) {
          await new Promise((r) => setTimeout(r, 400 * attempt));
          continue;
        }
        const text = await res.text();
        throw new ApiError(formatApiError(text, res.status), res.status);
      }
      if (res.status === 204) return undefined as T;
      return res.json();
    } catch (err) {
      if (init?.signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) {
        throw err;
      }
      lastError = err instanceof Error ? err : new Error(String(err));
      // Network blips — retry unless aborted
      if (attempt < maxAttempts && !(err instanceof ApiError)) {
        await new Promise((r) => setTimeout(r, 400 * attempt));
        continue;
      }
      // Already formatted API errors should not silently retry further
      if (attempt >= maxAttempts) break;
      if (err instanceof ApiError && [429, 502, 503, 504].includes(err.status)) {
        await new Promise((r) => setTimeout(r, 400 * attempt));
        continue;
      }
      throw lastError;
    }
  }
  throw lastError || new Error("Request failed");
}

export async function login(email: string, password: string) {
  const data = await api<{ access_token: string; user: User }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem("token", data.access_token);
  return data.user;
}

export async function register(email: string, password: string, name: string) {
  const data = await api<{ access_token: string; user: User }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
  localStorage.setItem("token", data.access_token);
  return data.user;
}

export async function fetchMe(): Promise<User> {
  return api("/auth/me");
}

export function logout() {
  clearToken();
}

function appendTenderFilterParams(params: URLSearchParams, filters: Filters): void {
  params.set("hide_outdated", String(!!filters.hide_outdated));
  params.set("hide_duplicates", String(!!filters.hide_duplicates));
  params.set("sort", optParam(filters.sort) || "published");
  // Always send match_any explicitly (backend default must not hide FE intent)
  params.set("match_any", filters.match_any ? "true" : "false");
  const q = optParam(filters.q);
  if (q) params.set("q", q);
  const exclude = optParam(filters.exclude);
  if (exclude) params.set("exclude", exclude);
  const source = optParam(filters.source);
  if (source) params.set("source", source);
  const law = optParam(filters.law);
  if (law) params.set("law", law);
  const region = optParam(filters.region);
  if (region) params.set("region", region);
  const method = optParam(filters.method);
  if (method) params.set("method", method);
  const okpd2 = optParam(filters.okpd2);
  if (okpd2) params.set("okpd2", okpd2);
  const status = optParam(filters.status_norm);
  if (status) params.set("status_norm", status);
  const minPrice = optParam(filters.min_price);
  if (minPrice) params.set("min_price", minPrice);
  const maxPrice = optParam(filters.max_price);
  if (maxPrice) params.set("max_price", maxPrice);
  const deadlineFrom = optParam(filters.deadline_from);
  if (deadlineFrom) params.set("deadline_from", deadlineFrom);
  const deadlineTo = optParam(filters.deadline_to);
  if (deadlineTo) params.set("deadline_to", deadlineTo);
}

export async function fetchTenders(
  filters: Filters,
  page: number,
  signal?: AbortSignal,
): Promise<TenderListResponse> {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", "20");
  appendTenderFilterParams(params, filters);
  return api(`/tenders?${params}`, { signal });
}

export async function fetchTender(id: number): Promise<Tender> {
  return api(`/tenders/${id}?enrich=true`);
}

export async function fetchChanges(id: number): Promise<TenderChange[]> {
  return api(`/tenders/${id}/changes`);
}

export async function fetchRelated(id: number): Promise<Tender[]> {
  return api(`/tenders/${id}/related`);
}

export async function fetchStats(): Promise<Stats> {
  return api("/stats");
}

export async function fetchDashboard(): Promise<Dashboard> {
  return api("/dashboard");
}

export async function fetchSources(): Promise<SourceInfo[]> {
  return api("/sources");
}

export async function fetchPresets(): Promise<FilterPreset[]> {
  return api("/presets");
}

export async function fetchMethods(): Promise<string[]> {
  return api("/meta/methods");
}

export async function fetchRegions(): Promise<string[]> {
  return api("/meta/regions");
}

export async function triggerScrape(sources?: string[]): Promise<unknown> {
  const data = await api<{ mode: string; job?: { id: number; status: string } }>("/scrape", {
    method: "POST",
    body: JSON.stringify(sources?.length ? { sources } : {}),
  });
  if (data.mode === "queued" && data.job?.id) {
    // Poll job briefly so UI waits for worker if it's running
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const job = await api<{ status: string; error?: string }>(`/jobs/${data.job!.id}`);
      if (job.status === "done" || job.status === "failed") return job;
    }
  }
  return data;
}

export async function fetchSourceMetrics(): Promise<SourceMetric[]> {
  return api("/metrics/sources");
}

export async function fetchMonitor(): Promise<MonitorSnapshot> {
  return api("/monitor");
}

export async function fetchCustomers(q = ""): Promise<Customer[]> {
  const params = q ? `?q=${encodeURIComponent(q)}` : "";
  return api(`/customers${params}`);
}

export async function fetchCustomer(id: number): Promise<Customer & { history: Tender[] }> {
  return api(`/customers/${id}`);
}

export async function checkTenderCompliance(id: number): Promise<ComplianceResult> {
  return api(`/tenders/${id}/compliance`, { method: "POST", body: "{}" });
}

export type SourceMetric = {
  source: string;
  display_name: string;
  last_status: string;
  last_ok_at: string | null;
  last_run_at: string | null;
  last_error: string | null;
  success_count: number;
  fallback_count: number;
  error_count: number;
  empty_count: number;
  consecutive_failures: number;
  success_rate: number;
  last_fetched: number;
  last_upserted: number;
  silent?: boolean;
  silent_for_minutes?: number | null;
  requires_api?: boolean;
  api_ready?: boolean;
  public_listing?: boolean;
  scrape_capable?: boolean;
};

export type MonitorSnapshot = {
  checked_at: string;
  silence_minutes: number;
  sources: SourceMetric[];
  unhealthy_count: number;
  alerts: { source: string; message: string }[];
};

export type SourceCredential = {
  source: string;
  label: string;
  api_url: string | null;
  token_configured: boolean;
  token_masked: string | null;
  configured: boolean;
  url_from_db: boolean;
  token_from_db: boolean;
  updated_at: string | null;
};

export type SourceCredentialTestResult = {
  ok: boolean;
  status_code: number | null;
  detail: string;
};

export async function fetchScrapeCredentials(): Promise<SourceCredential[]> {
  return api("/admin/scrape-credentials");
}

export async function saveScrapeCredential(
  source: string,
  payload: { api_url?: string | null; api_token?: string | null; clear_token?: boolean },
): Promise<SourceCredential> {
  return api(`/admin/scrape-credentials/${encodeURIComponent(source)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function testScrapeCredential(
  source: string,
  payload?: { api_url?: string | null; api_token?: string | null },
): Promise<SourceCredentialTestResult> {
  return api(`/admin/scrape-credentials/${encodeURIComponent(source)}/test`, {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}

export type Customer = {
  id: number;
  inn: string | null;
  kpp: string | null;
  name: string;
  holding_name: string | null;
  region: string | null;
  tender_count: number;
  total_price: number;
  in_rnp: boolean;
  has_bank_guarantee: boolean | null;
  compliance_notes: string | null;
};

export type ComplianceResult = {
  inn: string | null;
  in_rnp: boolean;
  has_bank_guarantee: boolean | null;
  notes: string;
  rnp_items: { id: number; title: string; url: string }[];
  guarantee_items: { id: number; title: string; url: string }[];
  customer_id: number | null;
};

export async function fetchProfile(): Promise<Profile> {
  return api("/profile");
}

export async function saveProfile(profile: Profile): Promise<Profile> {
  return api("/profile", { method: "PUT", body: JSON.stringify(profile) });
}

export async function saveTelegram(chatId: string | null): Promise<User> {
  return api("/profile/telegram", {
    method: "PUT",
    body: JSON.stringify({ telegram_chat_id: chatId }),
  });
}

export async function fetchWatches(): Promise<Watch[]> {
  return api("/watches");
}

export async function setWatch(
  tenderId: number,
  status: string,
  notes = "",
  tags: string[] = [],
): Promise<Watch> {
  return api(`/tenders/${tenderId}/watch`, {
    method: "POST",
    body: JSON.stringify({ status, notes, tags }),
  });
}

export async function fetchSavedSearches(): Promise<SavedSearch[]> {
  return api("/saved-searches");
}

export async function createSavedSearch(
  name: string,
  filters: Record<string, unknown>,
  notify_telegram = true,
): Promise<SavedSearch> {
  return api("/saved-searches", {
    method: "POST",
    body: JSON.stringify({ name, filters, notify_telegram }),
  });
}

export async function ackSavedSearch(id: number): Promise<SavedSearch> {
  return api(`/saved-searches/${id}/ack`, { method: "POST", body: "{}" });
}

export async function deleteSavedSearch(id: number): Promise<void> {
  await api(`/saved-searches/${id}`, { method: "DELETE" });
}

export function exportUrl(filters: Filters, format: "csv" | "xlsx"): string {
  const params = new URLSearchParams();
  params.set("format", format);
  appendTenderFilterParams(params, filters);
  return `${API}/tenders/export?${params}`;
}

export function asBool(value: unknown, defaultValue: boolean): boolean {
  if (value === undefined || value === null || value === "") return defaultValue;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const s = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(s)) return true;
  if (["0", "false", "no", "off"].includes(s)) return false;
  return defaultValue;
}

function cleanFilterStr(value: unknown, fallback = ""): string {
  if (value == null || value === "") return fallback;
  const s = String(value).trim();
  if (!s || s === "undefined" || s === "null" || s === "None") return fallback;
  return s;
}

export function presetToFilters(preset: FilterPreset): Filters {
  const f = preset.filters || {};
  return {
    ...emptyFilters,
    q: cleanFilterStr(f.q, emptyFilters.q),
    exclude: cleanFilterStr(f.exclude, emptyFilters.exclude),
    match_any: asBool(f.match_any, emptyFilters.match_any),
    source: cleanFilterStr(f.source),
    law: cleanFilterStr(f.law),
    region: cleanFilterStr(f.region),
    method: cleanFilterStr(f.method),
    okpd2: cleanFilterStr(f.okpd2),
    status_norm: cleanFilterStr(f.status_norm),
    min_price: cleanFilterStr(f.min_price),
    max_price: cleanFilterStr(f.max_price),
    deadline_from: cleanFilterStr(f.deadline_from),
    deadline_to: cleanFilterStr(f.deadline_to),
    hide_outdated: asBool(f.hide_outdated, true),
    hide_duplicates: asBool(f.hide_duplicates, true),
    sort: cleanFilterStr(f.sort, emptyFilters.sort),
  };
}

export function filtersToPayload(filters: Filters): Record<string, unknown> {
  return {
    q: optParam(filters.q) || undefined,
    exclude: optParam(filters.exclude) || undefined,
    match_any: filters.match_any,
    source: optParam(filters.source) || undefined,
    law: optParam(filters.law) || undefined,
    region: optParam(filters.region) || undefined,
    method: optParam(filters.method) || undefined,
    okpd2: optParam(filters.okpd2) || undefined,
    status_norm: optParam(filters.status_norm) || undefined,
    min_price: optParam(filters.min_price) || undefined,
    max_price: optParam(filters.max_price) || undefined,
    deadline_from: optParam(filters.deadline_from) || undefined,
    deadline_to: optParam(filters.deadline_to) || undefined,
    hide_outdated: filters.hide_outdated,
    hide_duplicates: filters.hide_duplicates,
    sort: optParam(filters.sort) || undefined,
  };
}

export function formatPrice(value: number | null | undefined, currency = "RUB"): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function sourceLabel(source: string, sources?: SourceInfo[]): string {
  const found = sources?.find((s) => s.id === source);
  if (found) return found.name;
  const map: Record<string, string> = {
    zakupki_44: "ЕИС · 44-ФЗ",
    zakupki_223: "ЕИС · 223-ФЗ",
    rts: "РТС-тендер",
    roseltorg: "Росэлторг",
    sber_ast: "Сбербанк-АСТ",
    b2b_center: "B2B-Center",
    etp_gpb: "ЭТП ГПБ",
    tektorg: "ТЕК-Торг",
    fabrikant: "Фабрикант",
    otc: "OTC-tender",
    agzrt: "АГЗ РТ",
    contour: "Контур.Закупки",
    tenderplan: "Tenderplan",
    tenderland: "Tenderland",
    synapse: "Synapse",
    rostender: "Rostender",
    torgi_gov: "torgi.gov.ru",
    rnp: "РНП (ЕИС)",
    bank_guarantees: "Банк гарантий (ЕИС)",
    fedresurs: "Федресурс",
    kartoteka: "Картотека",
  };
  return map[source] || source;
}
