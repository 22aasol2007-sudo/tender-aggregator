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

/** Default niche: refrigerated + general cargo (OR keywords). */
export const TRANSPORT_DEFAULT_Q =
  "рефрижератор рефтранспор хладотранспор изотерм температурн скоропортящ холодов охлажд заморож мороз грузоперевоз перевозк груз автоперевоз доставк груз транспортн услуг транспортно-экспедиц экспедирован фрахт логистик автотранспортн грузов автомоб перевозк автомобил перевозк продукц перевозк товар услуг по перевозк контейнерн перевоз фуры тентован трал негабаритн перевоз сборн груз 49.41 49.4 52.29";

export const TRANSPORT_DEFAULT_EXCLUDE =
  "программн обеспечен разработк сайт лицензи ПО антивирус серверн оборудов оргтехник канцеляр мебел офис уборк помещен охранн услуг";

export const emptyFilters: Filters = {
  q: TRANSPORT_DEFAULT_Q,
  exclude: TRANSPORT_DEFAULT_EXCLUDE,
  match_any: true,
  source: "",
  law: "",
  region: "",
  method: "",
  okpd2: "",
  status_norm: "accepting",
  min_price: "",
  max_price: "",
  deadline_from: "",
  deadline_to: "",
  hide_outdated: true,
  hide_duplicates: true,
  sort: "relevance",
};

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
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
  localStorage.removeItem("token");
}

export async function fetchTenders(filters: Filters, page: number): Promise<TenderListResponse> {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", "20");
  params.set("hide_outdated", String(filters.hide_outdated));
  params.set("hide_duplicates", String(filters.hide_duplicates));
  params.set("sort", filters.sort || "published");
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.exclude.trim()) params.set("exclude", filters.exclude.trim());
  if (filters.match_any) params.set("match_any", "true");
  if (filters.source) params.set("source", filters.source);
  if (filters.law) params.set("law", filters.law);
  if (filters.region.trim()) params.set("region", filters.region.trim());
  if (filters.method.trim()) params.set("method", filters.method.trim());
  if (filters.okpd2.trim()) params.set("okpd2", filters.okpd2.trim());
  if (filters.status_norm) params.set("status_norm", filters.status_norm);
  if (filters.min_price) params.set("min_price", filters.min_price);
  if (filters.max_price) params.set("max_price", filters.max_price);
  if (filters.deadline_from) params.set("deadline_from", filters.deadline_from);
  if (filters.deadline_to) params.set("deadline_to", filters.deadline_to);
  return api(`/tenders?${params}`);
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

export async function triggerScrape(): Promise<unknown> {
  const data = await api<{ mode: string; job?: { id: number; status: string } }>("/scrape", {
    method: "POST",
    body: "{}",
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
};

export type MonitorSnapshot = {
  checked_at: string;
  silence_minutes: number;
  sources: SourceMetric[];
  unhealthy_count: number;
  alerts: { source: string; message: string }[];
};

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
  params.set("hide_outdated", String(filters.hide_outdated));
  params.set("hide_duplicates", String(filters.hide_duplicates));
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.exclude.trim()) params.set("exclude", filters.exclude.trim());
  if (filters.match_any) params.set("match_any", "true");
  if (filters.source) params.set("source", filters.source);
  if (filters.law) params.set("law", filters.law);
  if (filters.region.trim()) params.set("region", filters.region.trim());
  if (filters.method.trim()) params.set("method", filters.method.trim());
  if (filters.okpd2.trim()) params.set("okpd2", filters.okpd2.trim());
  if (filters.status_norm) params.set("status_norm", filters.status_norm);
  if (filters.min_price) params.set("min_price", filters.min_price);
  if (filters.max_price) params.set("max_price", filters.max_price);
  return `${API}/tenders/export?${params}`;
}

export function presetToFilters(preset: FilterPreset): Filters {
  const f = preset.filters || {};
  return {
    ...emptyFilters,
    q: String(f.q ?? emptyFilters.q),
    exclude: String(f.exclude ?? emptyFilters.exclude),
    match_any: f.match_any !== false && f.match_any !== "false",
    source: String(f.source ?? ""),
    law: String(f.law ?? ""),
    region: String(f.region ?? ""),
    method: String(f.method ?? ""),
    okpd2: String(f.okpd2 ?? ""),
    status_norm: String(f.status_norm ?? "accepting"),
    min_price: f.min_price != null ? String(f.min_price) : "",
    max_price: f.max_price != null ? String(f.max_price) : "",
    hide_outdated: f.hide_outdated !== false,
    hide_duplicates: f.hide_duplicates !== false,
    sort: "relevance",
  };
}

export function filtersToPayload(filters: Filters): Record<string, unknown> {
  return {
    q: filters.q || undefined,
    exclude: filters.exclude || undefined,
    match_any: filters.match_any,
    source: filters.source || undefined,
    law: filters.law || undefined,
    region: filters.region || undefined,
    method: filters.method || undefined,
    okpd2: filters.okpd2 || undefined,
    status_norm: filters.status_norm || undefined,
    min_price: filters.min_price || undefined,
    max_price: filters.max_price || undefined,
    hide_outdated: filters.hide_outdated,
    hide_duplicates: filters.hide_duplicates,
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
