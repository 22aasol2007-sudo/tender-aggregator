import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  Dashboard,
  Filters,
  FilterPreset,
  Profile,
  SavedSearch,
  SourceCredential,
  SourceInfo,
  Stats,
  Tender,
  TenderChange,
  User,
  Watch,
  ackSavedSearch,
  checkTenderCompliance,
  createSavedSearch,
  deleteSavedSearch,
  applyNicheDefaults,
  emptyFilters,
  exportUrl,
  fetchChanges,
  fetchCustomer,
  fetchCustomers,
  fetchDashboard,
  fetchMe,
  fetchMethods,
  fetchMonitor,
  fetchNiche,
  fetchPresets,
  fetchProfile,
  fetchRegions,
  fetchRelated,
  fetchSavedSearches,
  fetchScrapeCredentials,
  fetchSourceMetrics,
  fetchSources,
  fetchStats,
  fetchTender,
  fetchTenders,
  fetchWatches,
  NicheConfig,
  filtersToPayload,
  formatDate,
  formatPrice,
  getToken,
  isAuthFailure,
  login,
  logout,
  presetToFilters,
  register,
  saveProfile,
  saveScrapeCredential,
  saveTelegram,
  setWatch,
  sourceLabel,
  testScrapeCredential,
  triggerScrape,
  ComplianceResult,
  Customer,
  MonitorSnapshot,
  SourceMetric,
  Contract,
  ContractAnalytics,
  fetchContracts,
  fetchContractAnalytics,
  triggerContractScrape,
  lookupMarketCache,
  ingestContractsToMarketCache,
  createRfq,
  fetchRfqDrafts,
  markRfqSent,
  MarketLookupResult,
  RfqResult,
} from "./api";

type Tab = "feed" | "dashboard" | "watches" | "searches" | "profile" | "monitor" | "customers" | "contracts";

export default function App() {
  const [tab, setTab] = useState<Tab>("feed");
  const [user, setUser] = useState<User | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");

  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [draft, setDraft] = useState<Filters>(emptyFilters);
  const [niche, setNiche] = useState<NicheConfig | null>(null);
  const [items, setItems] = useState<Tender[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [stats, setStats] = useState<Stats | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [methods, setMethods] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [metrics, setMetrics] = useState<SourceMetric[]>([]);
  const [monitor, setMonitor] = useState<MonitorSnapshot | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerQ, setCustomerQ] = useState("");
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [contractTotal, setContractTotal] = useState(0);
  const [contractStats, setContractStats] = useState<ContractAnalytics["stats"] | null>(null);
  const [topSuppliers, setTopSuppliers] = useState<ContractAnalytics["top_suppliers"]>([]);
  const [contractQ, setContractQ] = useState("");
  const [contractBusy, setContractBusy] = useState(false);
  const [cacheProduct, setCacheProduct] = useState("гофрокороб");
  const [cacheCity, setCacheCity] = useState("Москва");
  const [cacheQty, setCacheQty] = useState("5000");
  const [gofraFlute, setGofraFlute] = useState("3ply");
  const [gofraGrade, setGofraGrade] = useState("t23");
  const [gofraL, setGofraL] = useState("300");
  const [gofraW, setGofraW] = useState("200");
  const [gofraH, setGofraH] = useState("150");
  const [cacheResult, setCacheResult] = useState<MarketLookupResult | null>(null);
  const [cacheBusy, setCacheBusy] = useState(false);
  const [rfqBusy, setRfqBusy] = useState(false);
  const [rfqResult, setRfqResult] = useState<RfqResult | null>(null);
  const [rfqDrafts, setRfqDrafts] = useState<Array<Record<string, unknown>>>([]);
  const [rfqFormUrl, setRfqFormUrl] = useState<string | null>(null);
  const [compliance, setCompliance] = useState<ComplianceResult | null>(null);
  const [credStatus, setCredStatus] = useState<SourceCredential[]>([]);
  const [credDrafts, setCredDrafts] = useState<Record<string, { api_url: string; api_token: string }>>({});
  const [credBusy, setCredBusy] = useState<string | null>(null);
  const [credMsg, setCredMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Tender | null>(null);
  const [changes, setChanges] = useState<TenderChange[]>([]);
  const [related, setRelated] = useState<Tender[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [searchName, setSearchName] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const filterDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    void (async () => {
      const token = getToken();
      if (token) {
        try {
          const me = await fetchMe();
          setUser(me);
        } catch (err) {
          // Only drop session on real auth failure; keep token on network/API blips
          if (isAuthFailure(err)) {
            logout();
            setUser(null);
          }
        }
      } else {
        setUser(null);
      }
      try {
        const [src, pr, meth, reg, st, nicheCfg] = await Promise.all([
          fetchSources(),
          fetchPresets(),
          fetchMethods(),
          fetchRegions(),
          fetchStats(),
          fetchNiche().catch(() => null),
        ]);
        setSources(src);
        setPresets(pr);
        setMethods(meth);
        setRegions(reg);
        setStats(st);
        if (nicheCfg) {
          setNiche(nicheCfg);
          const next = applyNicheDefaults(nicheCfg);
          setFilters(next);
          setDraft(next);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось загрузить метаданные API");
      }
    })();
  }, []);

  const refreshStats = useCallback(async () => {
    try {
      setStats(await fetchStats());
    } catch {
      /* ignore */
    }
  }, []);

  async function load(nextPage = page, nextFilters = filters, withStats = false) {
    loadAbort.current?.abort();
    const ac = new AbortController();
    loadAbort.current = ac;
    setLoading(true);
    setError(null);
    try {
      const list = await fetchTenders(nextFilters, nextPage, ac.signal);
      if (ac.signal.aborted) return;
      setItems(list?.items ?? []);
      setTotal(list?.total ?? 0);
      setPage(list?.page ?? nextPage);
      if (withStats) await refreshStats();
    } catch (err) {
      if (ac.signal.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }

  // Single debounce: sync draft → filters then load (avoids double timers / stale match_any)
  useEffect(() => {
    if (tab !== "feed") return;
    if (filterDebounce.current) clearTimeout(filterDebounce.current);
    filterDebounce.current = setTimeout(() => {
      setFilters((prev) => {
        const next = { ...prev, ...draft };
        // Keep identity if nothing changed to avoid extra loops
        const same =
          prev.q === next.q &&
          prev.exclude === next.exclude &&
          prev.match_any === next.match_any &&
          prev.source === next.source &&
          prev.sort === next.sort &&
          prev.hide_outdated === next.hide_outdated &&
          prev.hide_duplicates === next.hide_duplicates &&
          prev.status_norm === next.status_norm &&
          prev.min_price === next.min_price &&
          prev.max_price === next.max_price &&
          prev.region === next.region &&
          prev.method === next.method &&
          prev.okpd2 === next.okpd2 &&
          prev.law === next.law &&
          prev.deadline_from === next.deadline_from &&
          prev.deadline_to === next.deadline_to;
        return same ? prev : next;
      });
    }, 350);
    return () => {
      if (filterDebounce.current) clearTimeout(filterDebounce.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, tab]);

  useEffect(() => {
    if (tab !== "feed") return;
    loadAbort.current?.abort();
    const ac = new AbortController();
    loadAbort.current = ac;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await fetchTenders(filters, 1, ac.signal);
        if (ac.signal.aborted) return;
        setItems(list?.items ?? []);
        setTotal(list?.total ?? 0);
        setPage(list?.page ?? 1);
      } catch (err) {
        if (ac.signal.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
        setError(err instanceof Error ? err.message : "Ошибка загрузки");
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    })();
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, tab]);

  useEffect(() => {
    if (tab === "dashboard") {
      void fetchDashboard().then(setDashboard).catch(() => setDashboard(null));
    }
    if (tab === "watches" && user) {
      void fetchWatches().then(setWatches).catch(() => setWatches([]));
    }
    if (tab === "searches" && user) {
      void fetchSavedSearches().then(setSearches).catch(() => setSearches([]));
    }
    if (tab === "profile" && user) {
      void fetchProfile().then(setProfile).catch(() => setProfile(null));
    }
    if (tab === "monitor") {
      void Promise.all([fetchSourceMetrics(), fetchMonitor()])
        .then(([m, mon]) => {
          setMetrics(m);
          setMonitor(mon);
        })
        .catch(() => {
          setMetrics([]);
          setMonitor(null);
        });
      if (user?.is_admin) {
        void fetchScrapeCredentials()
          .then((rows) => {
            setCredStatus(rows);
            setCredDrafts((prev) => {
              const next = { ...prev };
              for (const row of rows) {
                if (!next[row.source]) {
                  next[row.source] = { api_url: row.api_url || "", api_token: "" };
                } else {
                  next[row.source] = {
                    ...next[row.source],
                    api_url: next[row.source].api_url || row.api_url || "",
                  };
                }
              }
              return next;
            });
          })
          .catch(() => setCredStatus([]));
      }
    }
    if (tab === "customers") {
      void fetchCustomers(customerQ).then(setCustomers).catch(() => setCustomers([]));
    }
    if (tab === "contracts") {
      void (async () => {
        try {
          const [list, analytics] = await Promise.all([
            fetchContracts({ q: contractQ || undefined, page: 1, page_size: 30 }),
            fetchContractAnalytics({ q: contractQ || undefined, limit: 15 }),
          ]);
          setContracts(list.items);
          setContractTotal(list.total);
          setContractStats(analytics.stats);
          setTopSuppliers(analytics.top_suppliers);
        } catch {
          setContracts([]);
          setTopSuppliers([]);
        }
      })();
    }
  }, [tab, user, customerQ, contractQ]);

  async function onAuth(e: FormEvent) {
    e.preventDefault();
    if (authBusy) return;
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setError("Укажите email и пароль");
      return;
    }
    setAuthBusy(true);
    setError(null);
    try {
      const u =
        authMode === "login"
          ? await login(trimmedEmail, password)
          : await register(trimmedEmail, password, name.trim() || "Пользователь");
      setUser(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setAuthBusy(false);
    }
  }

  async function onScrape() {
    setScraping(true);
    setError(null);
    try {
      await triggerScrape();
      await load(1, filters, true);
      if (user) setSearches(await fetchSavedSearches());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка обновления");
    } finally {
      setScraping(false);
    }
  }

  async function onSaveCredential(source: string) {
    const draft = credDrafts[source] || { api_url: "", api_token: "" };
    setCredBusy(source);
    setCredMsg(null);
    setError(null);
    try {
      const payload: { api_url: string; api_token?: string } = { api_url: draft.api_url };
      if (draft.api_token.trim()) payload.api_token = draft.api_token.trim();
      const saved = await saveScrapeCredential(source, payload);
      setCredStatus((prev) => prev.map((r) => (r.source === source ? saved : r)));
      setCredDrafts((prev) => ({
        ...prev,
        [source]: { api_url: saved.api_url || "", api_token: "" },
      }));
      setCredMsg(
        saved.configured
          ? `${saved.label}: сохранено. Нажмите «Обновить сейчас», чтобы сбросить статус «нужен API».`
          : `${saved.label}: сохранено (нужны и URL, и токен).`,
      );
      const mon = await fetchMonitor();
      setMonitor(mon);
      setMetrics(mon.sources);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка сохранения API");
    } finally {
      setCredBusy(null);
    }
  }

  async function onTestCredential(source: string) {
    const draft = credDrafts[source] || { api_url: "", api_token: "" };
    setCredBusy(source);
    setCredMsg(null);
    setError(null);
    try {
      const result = await testScrapeCredential(source, {
        api_url: draft.api_url || undefined,
        api_token: draft.api_token.trim() || undefined,
      });
      setCredMsg(
        result.ok
          ? `${source}: соединение OK (${result.status_code})`
          : `${source}: ${result.detail}${result.status_code != null ? ` (${result.status_code})` : ""}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка проверки API");
    } finally {
      setCredBusy(null);
    }
  }

  async function onClearCredentialToken(source: string) {
    setCredBusy(source);
    setCredMsg(null);
    try {
      const draft = credDrafts[source] || { api_url: "", api_token: "" };
      const saved = await saveScrapeCredential(source, {
        api_url: draft.api_url,
        clear_token: true,
      });
      setCredStatus((prev) => prev.map((r) => (r.source === source ? saved : r)));
      setCredMsg(`${saved.label}: токен удалён из БД (останется env, если задан).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка очистки токена");
    } finally {
      setCredBusy(null);
    }
  }

  async function openDetail(t: Tender) {
    setSelected(t);
    setDetailLoading(true);
    try {
      const [full, ch, rel] = await Promise.all([
        fetchTender(t.id),
        fetchChanges(t.id),
        fetchRelated(t.id),
      ]);
      setSelected(full);
      setChanges(ch);
      setRelated(rel);
      try {
        setCompliance(await checkTenderCompliance(t.id));
      } catch {
        setCompliance(null);
      }
    } catch {
      /* keep */
    } finally {
      setDetailLoading(false);
    }
  }

  const pages = Math.max(1, Math.ceil(total / 20));

  const SORT_LABELS: Record<string, string> = {
    published: "По дате",
    relevance: "По релевантности",
    changed: "С изменениями",
  };
  const STATUS_LABELS: Record<string, string> = {
    accepting: "Приём заявок",
    completed: "Завершён",
    cancelled: "Отменён",
  };

  function truncateText(value: string, max = 42) {
    const t = value.trim();
    if (!t) return "";
    return t.length > max ? `${t.slice(0, max)}…` : t;
  }

  function resetToNicheDefaults() {
    if (filterDebounce.current) clearTimeout(filterDebounce.current);
    setDraft(emptyFilters);
    setFilters(emptyFilters);
    setPage(1);
  }

  function clearQueryOnly() {
    setDraft((d) => ({ ...d, q: "" }));
  }

  const activeFilterChips: { key: string; label: string; onClear?: () => void }[] = [];
  if (draft.q.trim()) {
    activeFilterChips.push({
      key: "q",
      label: `Запрос: ${truncateText(draft.q)}`,
      onClear: clearQueryOnly,
    });
  }
  activeFilterChips.push({
    key: "match",
    label: draft.match_any ? "Режим: любое слово (OR)" : "Режим: все слова (AND)",
  });
  activeFilterChips.push({
    key: "sort",
    label: `Сортировка: ${SORT_LABELS[draft.sort] || draft.sort}`,
  });
  if (draft.exclude.trim()) {
    activeFilterChips.push({
      key: "exclude",
      label: `Исключить: ${truncateText(draft.exclude, 28)}`,
      onClear: () => setDraft((d) => ({ ...d, exclude: "" })),
    });
  }
  if (draft.status_norm) {
    activeFilterChips.push({
      key: "status",
      label: `Статус: ${STATUS_LABELS[draft.status_norm] || draft.status_norm}`,
      onClear: () => setDraft((d) => ({ ...d, status_norm: "" })),
    });
  }
  if (draft.source) {
    const srcName = sources.find((s) => s.id === draft.source)?.name || draft.source;
    activeFilterChips.push({
      key: "source",
      label: `Источник: ${srcName}`,
      onClear: () => setDraft((d) => ({ ...d, source: "" })),
    });
  }
  if (draft.region.trim()) {
    activeFilterChips.push({
      key: "region",
      label: `Регион: ${truncateText(draft.region, 24)}`,
      onClear: () => setDraft((d) => ({ ...d, region: "" })),
    });
  }
  if (draft.method.trim()) {
    activeFilterChips.push({
      key: "method",
      label: `Способ: ${truncateText(draft.method, 24)}`,
      onClear: () => setDraft((d) => ({ ...d, method: "" })),
    });
  }
  if (draft.okpd2.trim()) {
    activeFilterChips.push({
      key: "okpd2",
      label: `ОКПД2: ${draft.okpd2}`,
      onClear: () => setDraft((d) => ({ ...d, okpd2: "" })),
    });
  }
  if (draft.law.trim()) {
    activeFilterChips.push({
      key: "law",
      label: `Закон: ${draft.law}`,
      onClear: () => setDraft((d) => ({ ...d, law: "" })),
    });
  }
  if (draft.min_price || draft.max_price) {
    activeFilterChips.push({
      key: "price",
      label: `НМЦК: ${draft.min_price || "…"} – ${draft.max_price || "…"}`,
      onClear: () => setDraft((d) => ({ ...d, min_price: "", max_price: "" })),
    });
  }
  if (draft.deadline_from || draft.deadline_to) {
    activeFilterChips.push({
      key: "deadline",
      label: `Срок: ${draft.deadline_from || "…"} – ${draft.deadline_to || "…"}`,
      onClear: () => setDraft((d) => ({ ...d, deadline_from: "", deadline_to: "" })),
    });
  }
  if (draft.hide_outdated) {
    activeFilterChips.push({ key: "hide_outdated", label: "Без устаревших" });
  }
  if (draft.hide_duplicates) {
    activeFilterChips.push({ key: "hide_duplicates", label: "Без дублей" });
  }

  const advancedActiveCount = [
    draft.exclude.trim(),
    draft.source,
    draft.law.trim(),
    draft.region.trim(),
    draft.method.trim(),
    draft.okpd2.trim(),
    draft.status_norm,
    draft.min_price,
    draft.max_price,
    draft.deadline_from,
    draft.deadline_to,
    draft.sort !== "relevance" ? draft.sort : "",
    !draft.match_any ? "and" : "",
    !draft.hide_outdated ? "show_old" : "",
    !draft.hide_duplicates ? "show_dups" : "",
  ].filter(Boolean).length;

  return (
    <div className="app-shell">
      <header className="hero">
        <h1 className="brand">
          Tender <span>Aggregator</span>
        </h1>
        <p className="hero-lead">
          Сбор каждые 5 мин, релевантность, избранное, сохранённые поиски, Telegram и дашборд.
        </p>
        <div className="hero-actions">
          <button className="btn btn-primary" onClick={onScrape} disabled={scraping}>
            {scraping ? "Обновляем…" : "Обновить сейчас"}
          </button>
          <span className="chip">БД: {stats?.database ?? "…"}</span>
          {user ? (
            <>
              <span className="chip chip-accent">{user.name}</span>
              <button
                className="btn btn-ghost"
                onClick={() => {
                  logout();
                  setUser(null);
                }}
              >
                Выйти
              </button>
            </>
          ) : null}
        </div>
        <nav className="tabs">
          {(
            [
              ["feed", "Лента"],
              ["dashboard", "Дашборд"],
              ["monitor", "Мониторинг"],
              ["customers", "Заказчики"],
              ["contracts", "Контракты"],
              ["watches", "В работу"],
              ["searches", "Поиски"],
              ["profile", "Профиль"],
            ] as [Tab, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              className={`tab ${tab === id ? "active" : ""}`}
              onClick={() => setTab(id)}
              type="button"
            >
              {label}
              {id === "searches" && searches.some((s) => s.new_count > 0)
                ? ` (${searches.reduce((a, s) => a + s.new_count, 0)})`
                : ""}
            </button>
          ))}
        </nav>
      </header>

      {!user && (
        <form className="auth-box" onSubmit={onAuth}>
          <h2>{authMode === "login" ? "Вход" : "Регистрация"}</h2>
          <p className="muted">Демо-аккаунт: admin@tender.local</p>
          {authMode === "register" && (
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя" />
          )}
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            autoComplete={authMode === "login" ? "current-password" : "new-password"}
          />
          {error && <p className="muted" style={{ color: "var(--danger, #c45c4a)", margin: 0 }}>{error}</p>}
          <div className="hero-actions">
            <button className="btn btn-primary" type="submit" disabled={authBusy}>
              {authBusy
                ? authMode === "login"
                  ? "Входим…"
                  : "Создаём…"
                : authMode === "login"
                  ? "Войти"
                  : "Создать аккаунт"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={authBusy}
              onClick={() => {
                setError(null);
                setAuthMode(authMode === "login" ? "register" : "login");
              }}
            >
              {authMode === "login" ? "Регистрация" : "У меня есть аккаунт"}
            </button>
          </div>
        </form>
      )}

      {error && (
        <div className="error">
          {error}
          <button
            type="button"
            className="btn btn-ghost"
            style={{ marginLeft: 12 }}
            onClick={() => {
              setError(null);
              if (tab === "feed") void load(page, filters, true);
              else if (tab === "dashboard") void fetchDashboard().then(setDashboard).catch(() => setDashboard(null));
              else if (tab === "monitor") {
                void Promise.all([fetchSourceMetrics(), fetchMonitor()])
                  .then(([m, mon]) => {
                    setMetrics(m || []);
                    setMonitor(mon);
                  })
                  .catch((err) => setError(err instanceof Error ? err.message : "Ошибка монитора"));
              }
            }}
          >
            Повторить
          </button>
        </div>
      )}

      {tab === "monitor" && (
        <section className="panel">
          <h3>Качество парсеров и тишина источников</h3>
          {monitor && (
            <p className="muted">
              Проверка: {formatDate(monitor.checked_at)} · порог тишины {monitor.silence_minutes} мин ·
              проблемных: {monitor.unhealthy_count}
              {monitor.alerts.length > 0 ? ` · алертов: ${monitor.alerts.length}` : ""}
              {" · "}
              Грузовые в базе: {monitor.freight_matched ?? "—"} / всего {monitor.total_tenders ?? "—"}
            </p>
          )}
          {monitor?.alerts && monitor.alerts.length > 0 && (
            <ul className="monitor-alerts">
              {monitor.alerts.map((a) => (
                <li key={`${a.source}-${a.message.slice(0, 40)}`}>{a.message}</li>
              ))}
            </ul>
          )}
          <div className="list">
            {(monitor?.sources || metrics).map((m) => (
              <article key={m.source} className="tender">
                <div>
                  <div className="tender-meta">
                    <span className="chip chip-accent">{m.display_name}</span>
                    <span className="chip">{m.last_status}</span>
                    <span className="chip">ok {m.success_rate}%</span>
                    {m.silent && <span className="chip chip-law">молчит</span>}
                    {m.last_status === "needs_api" && <span className="chip chip-law">нужен API</span>}
                    {m.last_status === "skipped" && !m.scrape_capable && (
                      <span className="chip chip-law">недоступен</span>
                    )}
                    {m.scrape_capable === false && m.last_status !== "needs_api" && m.last_status !== "skipped" && (
                      <span className="chip">без HTML</span>
                    )}
                  </div>
                  <p>
                    success {m.success_count} / fallback {m.fallback_count} / empty {m.empty_count} / err {m.error_count}
                    {" · "}
                    last ok {formatDate(m.last_ok_at)}
                  </p>
                  {m.last_error && <p className="muted">{m.last_error}</p>}
                </div>
                <div className="tender-side">
                  <div className="price" style={{ fontSize: "1rem" }}>{m.last_fetched} шт</div>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {tab === "monitor" && user?.is_admin && (
        <section className="panel profile-form" style={{ marginTop: "1rem" }}>
          <h3>API ключи сервисов</h3>
          <p className="muted">
            Значения из базы имеют приоритет над переменными окружения (CONTOUR_API_* и т.д.).
            После сохранения нажмите «Обновить сейчас», чтобы сбросить статус «нужен API».
            Токен после сохранения не показывается целиком — только маска.
            URL — JSON list/search endpoint (не HTML главной), например{" "}
            <code>https://api.example.com/v1/tenders</code>.
          </p>
          {credMsg && <p className="muted">{credMsg}</p>}
          {credStatus.map((row) => {
            const draft = credDrafts[row.source] || { api_url: row.api_url || "", api_token: "" };
            const busy = credBusy === row.source;
            return (
              <div key={row.source} className="cred-card">
                <div className="tender-meta" style={{ marginBottom: "0.4rem" }}>
                  <span className="chip chip-accent">{row.label}</span>
                  <span className="chip">{row.source}</span>
                  {row.configured ? (
                    <span className="chip">настроено</span>
                  ) : (
                    <span className="chip chip-law">нужен API</span>
                  )}
                  {row.token_configured && row.token_masked && (
                    <span className="chip">токен {row.token_masked}</span>
                  )}
                  {(row.url_from_db || row.token_from_db) && (
                    <span className="chip">из БД</span>
                  )}
                </div>
                <label>API URL</label>
                <input
                  value={draft.api_url}
                  placeholder="https://api…/v1/tenders (JSON list)"
                  onChange={(e) =>
                    setCredDrafts((prev) => ({
                      ...prev,
                      [row.source]: { ...draft, api_url: e.target.value },
                    }))
                  }
                />
                <span className="field-hint">
                  Формат: HTTPS JSON endpoint со списком (items/data/results). HTML-страница площадки не подойдёт.
                  {row.guide?.url_hint ? ` ${row.guide.url_hint}` : ""}
                </span>
                {row.guide && (
                  <details className="cred-guide">
                    <summary>Как получить ключ</summary>
                    {row.guide.paid_note && <p className="muted">{row.guide.paid_note}</p>}
                    <p className="muted">
                      Сайт:{" "}
                      <a href={row.guide.website} target="_blank" rel="noreferrer">
                        {row.guide.website}
                      </a>
                      {row.guide.signup_url && row.guide.signup_url !== row.guide.website && (
                        <>
                          {" · "}
                          <a href={row.guide.signup_url} target="_blank" rel="noreferrer">
                            API / заявка
                          </a>
                        </>
                      )}
                    </p>
                    <ol className="cred-guide-steps">
                      {row.guide.steps.map((step, i) => (
                        <li key={i}>{step}</li>
                      ))}
                    </ol>
                  </details>
                )}
                <label>API токен</label>
                <input
                  type="password"
                  autoComplete="off"
                  value={draft.api_token}
                  placeholder={
                    row.token_configured
                      ? `Сохранён: ${row.token_masked || "••••"} — оставьте пустым, чтобы не менять`
                      : "Вставьте токен"
                  }
                  onChange={(e) =>
                    setCredDrafts((prev) => ({
                      ...prev,
                      [row.source]: { ...draft, api_token: e.target.value },
                    }))
                  }
                />
                <div className="hero-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={busy}
                    onClick={() => void onSaveCredential(row.source)}
                  >
                    {busy ? "…" : "Сохранить"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy}
                    onClick={() => void onTestCredential(row.source)}
                  >
                    Проверить
                  </button>
                  {row.token_from_db && (
                    <button
                      className="btn"
                      type="button"
                      disabled={busy}
                      onClick={() => void onClearCredentialToken(row.source)}
                    >
                      Удалить токен из БД
                    </button>
                  )}
                  {row.configured && (
                    <button
                      className="btn"
                      type="button"
                      disabled={scraping || busy}
                      onClick={() => {
                        setScraping(true);
                        setError(null);
                        void triggerScrape([row.source])
                          .then(async () => {
                            setCredMsg(`${row.label}: сбор запущен.`);
                            const mon = await fetchMonitor();
                            setMonitor(mon);
                            setMetrics(mon.sources);
                          })
                          .catch((err) =>
                            setError(err instanceof Error ? err.message : "Ошибка обновления"),
                          )
                          .finally(() => setScraping(false));
                      }}
                    >
                      Обновить сейчас
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {tab === "customers" && (
        <section className="panel">
          <h3>Нормализованные заказчики</h3>
          <div className="hero-actions" style={{ marginBottom: "1rem" }}>
            <input
              placeholder="Поиск по имени / ИНН / холдингу"
              value={customerQ}
              onChange={(e) => setCustomerQ(e.target.value)}
            />
          </div>
          <div className="list">
            {customers.map((c) => (
              <article
                key={c.id}
                className="tender"
                onClick={() => void fetchCustomer(c.id).then((d) => {
                  setCustomers((prev) => prev.map((x) => (x.id === d.id ? d : x)));
                })}
              >
                <div>
                  <div className="tender-meta">
                    {c.holding_name && <span className="chip chip-accent">{c.holding_name}</span>}
                    {c.inn && <span className="chip">ИНН {c.inn}</span>}
                    {c.kpp && <span className="chip">КПП {c.kpp}</span>}
                    {c.in_rnp && <span className="chip chip-law">РНП</span>}
                    {c.has_bank_guarantee && <span className="chip">Гарантия</span>}
                  </div>
                  <h2>{c.name}</h2>
                  <p>
                    {c.region || "—"} · закупок: {c.tender_count} · сумма: {formatPrice(c.total_price)}
                  </p>
                  {c.compliance_notes && <p className="muted">{c.compliance_notes}</p>}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {tab === "contracts" && (
        <section className="panel">
          <h3>История контрактов и победители</h3>
          <p className="muted">
            Цена контракта (не НМЦК) + кто выигрывал. Поиск по предмету / ОКПД / поставщику.
          </p>
          <div className="hero-actions" style={{ marginBottom: "1rem", flexWrap: "wrap" }}>
            <input
              placeholder="например: полиэтилен, 22.21, перевозка"
              value={contractQ}
              onChange={(e) => setContractQ(e.target.value)}
              style={{ minWidth: "240px", flex: 1 }}
            />
            {user?.is_admin && (
              <button
                className="btn btn-ghost"
                type="button"
                disabled={contractBusy}
                onClick={() => {
                  setContractBusy(true);
                  void triggerContractScrape(contractQ || undefined)
                    .then(() => setError(null))
                    .catch((err) => setError(err instanceof Error ? err.message : "Скрап контрактов не удался"))
                    .finally(() => setContractBusy(false));
                }}
              >
                {contractBusy ? "Запуск…" : "Обновить из ЕИС"}
              </button>
            )}
          </div>
          {contractStats && (
            <div className="stats" style={{ marginBottom: "1rem" }}>
              <div className="stat">
                <div className="stat-label">Контрактов</div>
                <div className="stat-value">{contractStats.count ?? contractTotal}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Медиана цены</div>
                <div className="stat-value" style={{ fontSize: "1.05rem" }}>
                  {formatPrice(contractStats.median_price ?? null)}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">P25–P75</div>
                <div className="stat-value" style={{ fontSize: "0.95rem" }}>
                  {formatPrice(contractStats.p25_price ?? null)} – {formatPrice(contractStats.p75_price ?? null)}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Ср. снижение от НМЦК</div>
                <div className="stat-value" style={{ fontSize: "1.05rem" }}>
                  {contractStats.avg_discount_pct != null
                    ? `${contractStats.avg_discount_pct.toFixed(1)}%`
                    : "—"}
                </div>
              </div>
            </div>
          )}

          <div className="panel" style={{ marginBottom: "1rem" }}>
            <h3>Кэш рынка + RFQ (ниша: косметика × гофра, Москва)</h3>
            <p className="muted">
              Observed/estimate — ориентир. Сделку подтверждаем только по firm (ответ поставщика).
              Пилот: k-anonymity N=3. Карантин не прячет демпинг — показываем отдельно.
            </p>
            <div className="hero-actions" style={{ flexWrap: "wrap", marginBottom: "0.5rem" }}>
              <input
                placeholder="товар"
                value={cacheProduct}
                onChange={(e) => setCacheProduct(e.target.value)}
                style={{ minWidth: "140px" }}
              />
              <input
                placeholder="город"
                value={cacheCity}
                onChange={(e) => setCacheCity(e.target.value)}
                style={{ minWidth: "100px" }}
              />
              <input
                placeholder="qty"
                value={cacheQty}
                onChange={(e) => setCacheQty(e.target.value)}
                style={{ width: "90px" }}
              />
              <input
                placeholder="flute"
                value={gofraFlute}
                onChange={(e) => setGofraFlute(e.target.value)}
                style={{ width: "80px" }}
                title="3ply / 5ply / e / b"
              />
              <input
                placeholder="grade"
                value={gofraGrade}
                onChange={(e) => setGofraGrade(e.target.value)}
                style={{ width: "70px" }}
              />
              <input
                placeholder="L"
                value={gofraL}
                onChange={(e) => setGofraL(e.target.value)}
                style={{ width: "60px" }}
              />
              <input
                placeholder="W"
                value={gofraW}
                onChange={(e) => setGofraW(e.target.value)}
                style={{ width: "60px" }}
              />
              <input
                placeholder="H"
                value={gofraH}
                onChange={(e) => setGofraH(e.target.value)}
                style={{ width: "60px" }}
              />
            </div>
            <div className="hero-actions" style={{ flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <button
                className="btn btn-primary"
                type="button"
                disabled={cacheBusy || !cacheProduct.trim()}
                onClick={() => {
                  setCacheBusy(true);
                  const attrs: Record<string, unknown> = {};
                  if (gofraFlute.trim()) attrs.flute = gofraFlute.trim();
                  if (gofraGrade.trim()) attrs.grade = gofraGrade.trim();
                  if (gofraL.trim()) attrs.length_mm = Number(gofraL);
                  if (gofraW.trim()) attrs.width_mm = Number(gofraW);
                  if (gofraH.trim()) attrs.height_mm = Number(gofraH);
                  void lookupMarketCache({
                    product: cacheProduct.trim(),
                    city: cacheCity.trim() || undefined,
                    qty: cacheQty ? Number(cacheQty) : undefined,
                    unit: "шт",
                    attrs,
                    niche_pilot: true,
                    private_only: profile?.private_only,
                  })
                    .then(setCacheResult)
                    .catch((err) => setError(err instanceof Error ? err.message : "Кэш недоступен"))
                    .finally(() => setCacheBusy(false));
                }}
              >
                {cacheBusy ? "Проверка…" : "Проверить кэш"}
              </button>
              {user && (
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={rfqBusy || !cacheProduct.trim()}
                  onClick={() => {
                    setRfqBusy(true);
                    const attrs: Record<string, unknown> = {};
                    if (gofraFlute.trim()) attrs.flute = gofraFlute.trim();
                    if (gofraGrade.trim()) attrs.grade = gofraGrade.trim();
                    if (gofraL.trim()) attrs.length_mm = Number(gofraL);
                    if (gofraW.trim()) attrs.width_mm = Number(gofraW);
                    if (gofraH.trim()) attrs.height_mm = Number(gofraH);
                    void createRfq({
                      product: cacheProduct.trim(),
                      city: cacheCity.trim() || "Москва",
                      qty: cacheQty ? Number(cacheQty) : undefined,
                      unit: "шт",
                      attrs,
                    })
                      .then(async (rfq) => {
                        setRfqResult(rfq);
                        setRfqFormUrl(rfq.form_url || null);
                        const d = await fetchRfqDrafts(rfq.id);
                        setRfqDrafts(d.drafts || []);
                        setRfqFormUrl(d.form_url || rfq.form_url || null);
                      })
                      .catch((err) => setError(err instanceof Error ? err.message : "RFQ ошибка"))
                      .finally(() => setRfqBusy(false));
                  }}
                >
                  {rfqBusy ? "RFQ…" : "Создать RFQ (warm-first)"}
                </button>
              )}
              {user?.is_admin && (
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={cacheBusy}
                  onClick={() => {
                    setCacheBusy(true);
                    void ingestContractsToMarketCache(contractQ || cacheProduct, cacheCity || undefined)
                      .then((r) => {
                        setError(null);
                        setCacheResult({
                          hit: true,
                          reason: "ingested",
                          fingerprint: "—",
                          offers: [],
                          offer_count: r.offers_saved,
                          summary: { queries_touched: r.queries_touched, offers_saved: r.offers_saved },
                        });
                      })
                      .catch((err) => setError(err instanceof Error ? err.message : "Ingest не удался"))
                      .finally(() => setCacheBusy(false));
                  }}
                >
                  Залить контракты в кэш
                </button>
              )}
            </div>
            {cacheResult && (
              <div>
                <p>
                  {cacheResult.hit ? (
                    <>
                      <strong>HIT</strong> ({cacheResult.match_type || cacheResult.reason})
                      {cacheResult.freshness ? ` · freshness: ${cacheResult.freshness}` : ""}
                      {cacheResult.age_days != null ? ` · возраст ${cacheResult.age_days}д` : ""}
                      {cacheResult.ttl_days != null ? ` / TTL ${cacheResult.ttl_days}д` : ""}
                      {cacheResult.tokens_saved_this_hit != null &&
                        cacheResult.tokens_saved_this_hit > 0 &&
                        ` · ~${cacheResult.tokens_saved_this_hit.toLocaleString("ru-RU")} токенов`}
                    </>
                  ) : (
                    <>
                      <strong>{cacheResult.match_type === "soft" ? "SOFT HINT" : "MISS"}</strong> (
                      {cacheResult.reason})
                      {cacheResult.warning ? ` — ${cacheResult.warning}` : " — создайте RFQ"}
                    </>
                  )}
                </p>
                {cacheResult.price_layers_note && <p className="muted">{cacheResult.price_layers_note}</p>}
                {cacheResult.warning && cacheResult.hit && <p className="muted">{cacheResult.warning}</p>}
                {cacheResult.offers?.length > 0 && (
                  <div className="list">
                    {cacheResult.offers.slice(0, 8).map((o, idx) => (
                      <article key={o.id ?? idx} className="tender">
                        <div>
                          <div className="tender-meta">
                            <span className="chip chip-accent">{o.price_layer || "observed"}</span>
                            <span className="chip">{o.source_type}</span>
                            {o.freshness && <span className="chip">{o.freshness}</span>}
                            {o.trust_score != null && (
                              <span className="chip">trust {Math.round(o.trust_score * 100)}%</span>
                            )}
                            {o.incomparable && <span className="chip chip-law">не сравнимо</span>}
                            {o.supplier_inn && <span className="chip">ИНН {o.supplier_inn}</span>}
                          </div>
                          <h2>{o.supplier_name || "Поставщик"}</h2>
                          <p>
                            цена: {formatPrice(o.landed_unit_price ?? o.price_value ?? null)}
                            {o.unit ? ` / ${o.unit}` : ""}
                            {o.city_to ? ` · ${o.city_to}` : ""}
                            {o.age_days != null ? ` · ${o.age_days}д назад` : ""}
                          </p>
                          {o.disclaimer && <p className="muted">{o.disclaimer}</p>}
                          {o.price_layer !== "firm" && (
                            <p className="muted">Hard-gate: нельзя подтвердить сделку по observed/estimate.</p>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
                {(cacheResult.quarantine_offers?.length ?? 0) > 0 && (
                  <div style={{ marginTop: "0.75rem" }}>
                    <h4>Карантин (возможен честный демпинг — вручную)</h4>
                    <div className="list">
                      {cacheResult.quarantine_offers!.slice(0, 5).map((o, idx) => (
                        <article key={(o.id as number) ?? idx} className="tender">
                          <div>
                            <div className="tender-meta">
                              <span className="chip chip-law">quarantine</span>
                              <span className="chip">{String(o.quarantine_reason || "")}</span>
                            </div>
                            <h2>{String(o.supplier_name || "Поставщик")}</h2>
                            <p className="muted">{String(o.dumping_note || "")}</p>
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {rfqResult && (
              <div style={{ marginTop: "1rem" }}>
                <h4>
                  RFQ #{rfqResult.id} · {rfqResult.status} · targets {rfqResult.targets_count ?? "—"}
                </h4>
                {rfqFormUrl && (
                  <p className="muted">
                    Форма для поставщика: <code>{rfqFormUrl}</code>
                  </p>
                )}
                <div className="hero-actions" style={{ marginBottom: "0.5rem" }}>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => {
                      void markRfqSent(rfqResult.id)
                        .then(setRfqResult)
                        .catch((err) => setError(err instanceof Error ? err.message : "mark-sent failed"));
                    }}
                  >
                    Отметить отправленным
                  </button>
                </div>
                {rfqDrafts.length > 0 && (
                  <div className="list">
                    {rfqDrafts.slice(0, 6).map((d, idx) => (
                      <article key={(d.target_id as number) ?? idx} className="tender">
                        <div>
                          <div className="tender-meta">
                            <span className="chip chip-accent">{d.warm ? "warm" : "cold"}</span>
                            <span className="chip">{String(d.channel || "manual")}</span>
                            <span className="chip">{String(d.source || "")}</span>
                          </div>
                          <h2>{String(d.supplier_name || "Поставщик")}</h2>
                          <p className="muted" style={{ whiteSpace: "pre-wrap" }}>
                            {String(d.body || "").slice(0, 280)}
                            {String(d.body || "").length > 280 ? "…" : ""}
                          </p>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="dash-grid">
            <div className="panel">
              <h3>Топ поставщиков по победам</h3>
              <div className="list">
                {topSuppliers.length === 0 && <p className="muted">Пока нет данных — запустите сбор или дождитесь seed.</p>}
                {topSuppliers.map((s, idx) => (
                  <article key={`${s.supplier_inn || s.supplier_name}-${idx}`} className="tender">
                    <div>
                      <div className="tender-meta">
                        <span className="chip chip-accent">{s.wins} побед</span>
                        {s.supplier_inn && <span className="chip">ИНН {s.supplier_inn}</span>}
                        {s.avg_discount_pct != null && (
                          <span className="chip">−{s.avg_discount_pct.toFixed(1)}% к НМЦК</span>
                        )}
                      </div>
                      <h2>{s.supplier_name || "Без названия"}</h2>
                      <p>
                        ср. цена: {formatPrice(s.avg_price)} · сумма: {formatPrice(s.total_price)}
                        {s.last_won_at ? ` · последний: ${formatDate(s.last_won_at)}` : ""}
                      </p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3>Контракты ({contractTotal})</h3>
              <div className="list">
                {contracts.map((c) => (
                  <article key={c.id} className="tender">
                    <div>
                      <div className="tender-meta">
                        {c.law && <span className="chip chip-law">{c.law}</span>}
                        {c.okpd2 && <span className="chip">ОКПД {c.okpd2}</span>}
                        {c.discount_pct != null && (
                          <span className="chip">−{c.discount_pct.toFixed(1)}%</span>
                        )}
                        <span className="chip">{sourceLabel(c.source, sources)}</span>
                      </div>
                      <h2>
                        <a href={c.url} target="_blank" rel="noreferrer">
                          {c.title}
                        </a>
                      </h2>
                      <p>
                        Победитель: <strong>{c.supplier_name || "—"}</strong>
                        {c.supplier_inn ? ` (ИНН ${c.supplier_inn})` : ""}
                      </p>
                      <p>
                        Цена контракта: {formatPrice(c.price)}
                        {c.nmck != null ? ` · НМЦК: ${formatPrice(c.nmck)}` : ""}
                        {c.region ? ` · ${c.region}` : ""}
                        {c.signed_at ? ` · ${formatDate(c.signed_at)}` : ""}
                      </p>
                      {c.customer && <p className="muted">Заказчик: {c.customer}</p>}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {tab === "dashboard" && dashboard && (
        <section className="dash">
          <div className="stats">
            <div className="stat"><div className="stat-label">Активных</div><div className="stat-value">{dashboard.active}</div></div>
            <div className="stat"><div className="stat-label">Новых за день</div><div className="stat-value">{dashboard.new_day}</div></div>
            <div className="stat"><div className="stat-label">Изменений за день</div><div className="stat-value">{dashboard.changed_day}</div></div>
            <div className="stat"><div className="stat-label">Средняя НМЦК</div><div className="stat-value" style={{ fontSize: "1.1rem" }}>{formatPrice(dashboard.avg_price)}</div></div>
          </div>
          <div className="dash-grid">
            <div className="panel">
              <h3>Динамика за 7 дней</h3>
              <div className="bars">
                {dashboard.series.map((s) => (
                  <div key={s.date} className="bar-wrap" title={`${s.date}: ${s.count}`}>
                    <div className="bar" style={{ height: `${Math.max(8, s.count * 4)}px` }} />
                    <span>{s.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3>Топ регионов</h3>
              <ul>
                {dashboard.top_regions.map((r) => (
                  <li key={r.region}>{r.region}: {r.count}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {tab === "watches" && (
        <section className="list">
          {!user && <div className="empty">Войдите, чтобы вести избранное и статусы.</div>}
          {user && watches.length === 0 && <div className="empty">Пока пусто — отметьте тендер в карточке.</div>}
          {watches.map((w) =>
            w.tender ? (
              <article key={w.id} className="tender" onClick={() => void openDetail(w.tender!)}>
                <div>
                  <div className="tender-meta">
                    <span className="chip chip-accent">{w.status}</span>
                    {(w.tags || []).map((t) => (
                      <span className="chip" key={t}>{t}</span>
                    ))}
                  </div>
                  <h2>{w.tender.title}</h2>
                  <p>{w.notes || w.tender.customer || "—"}</p>
                </div>
                <div className="tender-side">
                  <div className="price">{formatPrice(w.tender.price)}</div>
                </div>
              </article>
            ) : null,
          )}
        </section>
      )}

      {tab === "searches" && (
        <section className="panel">
          {!user && <div className="empty">Войдите, чтобы сохранять поиски и получать алерты.</div>}
          {user && (
            <>
              <div className="hero-actions" style={{ marginBottom: "1rem" }}>
                <input
                  placeholder="Название поиска"
                  value={searchName}
                  onChange={(e) => setSearchName(e.target.value)}
                />
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={async () => {
                    if (!searchName.trim()) return;
                    try {
                      await createSavedSearch(searchName.trim(), filtersToPayload(draft), true);
                      setSearchName("");
                      setSearches(await fetchSavedSearches());
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Не удалось сохранить поиск");
                    }
                  }}
                >
                  Сохранить текущие фильтры
                </button>
              </div>
              <div className="list">
                {searches.map((s) => (
                  <article key={s.id} className="tender">
                    <div>
                      <div className="tender-meta">
                        <span className="chip chip-accent">{s.name}</span>
                        {s.new_count > 0 && <span className="chip chip-law">+{s.new_count} новых</span>}
                        {s.notify_telegram && <span className="chip">Telegram</span>}
                      </div>
                      <p className="muted">{JSON.stringify(s.filters)}</p>
                    </div>
                    <div className="tender-side">
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => {
                          const next = presetToFilters({
                            id: s.id,
                            name: s.name,
                            description: null,
                            filters: s.filters,
                            is_builtin: false,
                          });
                          setDraft(next);
                          setFilters(next);
                          setTab("feed");
                          void ackSavedSearch(s.id)
                            .then(async () => setSearches(await fetchSavedSearches()))
                            .catch((err) =>
                              setError(err instanceof Error ? err.message : "Ошибка подтверждения"),
                            );
                        }}
                      >
                        Открыть
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={async () => {
                          try {
                            await deleteSavedSearch(s.id);
                            setSearches(await fetchSavedSearches());
                          } catch (err) {
                            setError(err instanceof Error ? err.message : "Не удалось удалить поиск");
                          }
                        }}
                      >
                        Удалить
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {tab === "profile" && user && profile && (
        <section className="panel profile-form">
          <h3>Профиль компании (релевантность)</h3>
          <label>Компания</label>
          <input
            value={profile.company_name || ""}
            onChange={(e) => setProfile({ ...profile, company_name: e.target.value })}
          />
          <label>ОКПД префиксы (через запятую)</label>
          <input
            value={(profile.okpd_prefixes || []).join(", ")}
            onChange={(e) =>
              setProfile({
                ...profile,
                okpd_prefixes: e.target.value.split(",").map((x) => x.trim()).filter(Boolean),
              })
            }
          />
          <label>Регионы (через запятую)</label>
          <input
            value={(profile.regions || []).join(", ")}
            onChange={(e) =>
              setProfile({
                ...profile,
                regions: e.target.value.split(",").map((x) => x.trim()).filter(Boolean),
              })
            }
          />
          <label>Ключевые слова</label>
          <input
            value={(profile.keywords || []).join(", ")}
            onChange={(e) =>
              setProfile({
                ...profile,
                keywords: e.target.value.split(",").map((x) => x.trim()).filter(Boolean),
              })
            }
          />
          <label>НМЦК от / до</label>
          <div className="hero-actions">
            <input
              type="number"
              value={profile.min_price ?? ""}
              onChange={(e) =>
                setProfile({ ...profile, min_price: e.target.value ? Number(e.target.value) : null })
              }
            />
            <input
              type="number"
              value={profile.max_price ?? ""}
              onChange={(e) =>
                setProfile({ ...profile, max_price: e.target.value ? Number(e.target.value) : null })
              }
            />
          </div>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.75rem" }}>
            <input
              type="checkbox"
              checked={Boolean(profile.private_only)}
              onChange={(e) =>
                setProfile({
                  ...profile,
                  private_only: e.target.checked,
                  share_consent: e.target.checked ? false : profile.share_consent,
                })
              }
            />
            Private-only (ИБ запретил share — только своя база/RFQ)
          </label>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={Boolean(profile.share_consent) && !profile.private_only}
              disabled={Boolean(profile.private_only)}
              onChange={(e) => setProfile({ ...profile, share_consent: e.target.checked })}
            />
            Share consent (обезличенные observed в общий кэш ниши)
          </label>
          <p className="muted">Ниша по умолчанию: cosmetics_moscow_gofra · 90 дней только гофра/картон.</p>
          <label>Telegram chat id</label>
          <input
            value={user.telegram_chat_id || ""}
            onChange={(e) => setUser({ ...user, telegram_chat_id: e.target.value })}
            placeholder="123456789"
          />
          <div className="hero-actions">
            <button
              className="btn btn-primary"
              type="button"
              onClick={async () => {
                setProfile(await saveProfile(profile));
                setUser(await saveTelegram(user.telegram_chat_id));
              }}
            >
              Сохранить
            </button>
          </div>
          <p className="muted">
            Для алертов задайте TELEGRAM_BOT_TOKEN в backend/.env и chat id здесь.
          </p>
        </section>
      )}

      {tab === "feed" && (
        <>
          <section className="stats">
            <div className="stat"><div className="stat-label">Активных</div><div className="stat-value">{stats?.active ?? "—"}</div></div>
            <div className="stat"><div className="stat-label">Всего</div><div className="stat-value">{stats?.total ?? "—"}</div></div>
            <div className="stat"><div className="stat-label">Последний сбор</div><div className="stat-value" style={{ fontSize: "1.05rem" }}>{formatDate(stats?.last_scrape)}</div></div>
          </section>

          <p className="muted" style={{ margin: "0.35rem 0 0.75rem" }}>
            Найдено {total.toLocaleString("ru-RU")}
            {stats != null ? ` / в базе ${stats.total.toLocaleString("ru-RU")}` : ""}
            {loading ? " …" : ""}
          </p>

          <div className="presets">
            {presets.map((p) => (
              <button key={p.id} type="button" className="preset-chip" onClick={() => { const n = presetToFilters(p); setDraft(n); setFilters(n); }}>
                {p.name}
              </button>
            ))}
            {niche?.presets?.maximum && !presets.some((p) => p.name === niche.presets.maximum.name) && (
              <button
                type="button"
                className="preset-chip"
                onClick={() => {
                  const n = {
                    ...emptyFilters,
                    q: niche.presets.maximum.q,
                    exclude: niche.presets.maximum.exclude || emptyFilters.exclude,
                    match_any: niche.presets.maximum.match_any !== false,
                  };
                  setDraft(n);
                  setFilters(n);
                }}
              >
                {niche.presets.maximum.name}
              </button>
            )}
            <a className="preset-chip ghost" href={exportUrl(draft, "csv")}>CSV</a>
            <a className="preset-chip ghost" href={exportUrl(draft, "xlsx")}>Excel</a>
          </div>

          <form
            className="search-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (filterDebounce.current) clearTimeout(filterDebounce.current);
              setPage(1);
              setFilters(draft);
            }}
          >
            <div className="search-primary">
              <div className="field grow">
                <label htmlFor="search-q">Поиск тендеров</label>
                <input
                  id="search-q"
                  value={draft.q}
                  onChange={(e) => setDraft({ ...draft, q: e.target.value })}
                  placeholder="рефрижератор, перевозка грузов — через запятую = отдельные фразы (ИЛИ)"
                  autoComplete="off"
                />
                <span className="field-hint">
                  Запятая разделяет фразы: подходит тендер с любой из них. Пустой запрос — без текстового фильтра.
                </span>
              </div>
              <div className="search-primary-actions">
                <button className="btn btn-primary" type="submit">
                  Найти
                </button>
              </div>
            </div>

            <div className="active-filters" aria-label="Активные фильтры">
              <div className="active-filters-chips">
                {activeFilterChips.map((chip) => (
                  <span key={chip.key} className="filter-chip">
                    {chip.label}
                    {chip.onClear ? (
                      <button
                        type="button"
                        className="filter-chip-clear"
                        aria-label={`Убрать: ${chip.label}`}
                        onClick={chip.onClear}
                      >
                        ×
                      </button>
                    ) : null}
                  </span>
                ))}
              </div>
              <button className="btn btn-ghost btn-sm" type="button" onClick={resetToNicheDefaults}>
                Сбросить
              </button>
            </div>

            <button
              type="button"
              className={`advanced-toggle ${advancedOpen ? "open" : ""}`}
              onClick={() => setAdvancedOpen((v) => !v)}
              aria-expanded={advancedOpen}
            >
              <span>Дополнительно</span>
              {advancedActiveCount > 0 && (
                <span className="advanced-count">{advancedActiveCount}</span>
              )}
              <span className="advanced-chevron" aria-hidden>
                {advancedOpen ? "▴" : "▾"}
              </span>
            </button>

            {advancedOpen && (
              <div className="filters-advanced">
                <div className="field grow">
                  <label htmlFor="search-exclude">Исключить слова</label>
                  <input
                    id="search-exclude"
                    value={draft.exclude}
                    onChange={(e) => setDraft({ ...draft, exclude: e.target.value })}
                    placeholder="ПО, канцелярия — убрать из выдачи"
                  />
                  <span className="field-hint">Тендеры с этими словами не попадут в список (через запятую).</span>
                </div>

                <div className="field checks-block">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={draft.match_any}
                      onChange={(e) => setDraft({ ...draft, match_any: e.target.checked })}
                    />
                    Любое из слов (OR)
                  </label>
                  <span className="field-hint">
                    {draft.match_any
                      ? "Достаточно совпадения с одной фразой из запроса."
                      : "Нужны все фразы сразу (AND) — выдача уже."}
                  </span>
                </div>

                <div className="field">
                  <label>Сортировка</label>
                  <select value={draft.sort} onChange={(e) => setDraft({ ...draft, sort: e.target.value })}>
                    <option value="published">По дате</option>
                    <option value="relevance">По релевантности</option>
                    <option value="changed">С изменениями</option>
                  </select>
                </div>

                <div className="field">
                  <label>Статус</label>
                  <select value={draft.status_norm} onChange={(e) => setDraft({ ...draft, status_norm: e.target.value })}>
                    <option value="">Все</option>
                    <option value="accepting">Приём заявок</option>
                    <option value="completed">Завершён</option>
                    <option value="cancelled">Отменён</option>
                  </select>
                </div>

                <div className="field">
                  <label>Источник</label>
                  <select value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
                    <option value="">Все</option>
                    {sources.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>Регион</label>
                  <input
                    list="regions"
                    value={draft.region}
                    onChange={(e) => setDraft({ ...draft, region: e.target.value })}
                    placeholder="Например, Москва"
                  />
                  <datalist id="regions">{regions.map((r) => <option key={r} value={r} />)}</datalist>
                </div>

                <div className="field">
                  <label>Способ закупки</label>
                  <input
                    list="methods"
                    value={draft.method}
                    onChange={(e) => setDraft({ ...draft, method: e.target.value })}
                  />
                  <datalist id="methods">{methods.map((m) => <option key={m} value={m} />)}</datalist>
                </div>

                <div className="field">
                  <label>ОКПД2</label>
                  <input
                    value={draft.okpd2}
                    onChange={(e) => setDraft({ ...draft, okpd2: e.target.value })}
                    placeholder="49.41"
                  />
                </div>

                <div className="field">
                  <label>Закон</label>
                  <select value={draft.law} onChange={(e) => setDraft({ ...draft, law: e.target.value })}>
                    <option value="">Все</option>
                    <option value="44-ФЗ">44-ФЗ</option>
                    <option value="223-ФЗ">223-ФЗ</option>
                  </select>
                </div>

                <div className="field">
                  <label>НМЦК от</label>
                  <input
                    type="number"
                    value={draft.min_price}
                    onChange={(e) => setDraft({ ...draft, min_price: e.target.value })}
                    placeholder="0"
                  />
                </div>

                <div className="field">
                  <label>НМЦК до</label>
                  <input
                    type="number"
                    value={draft.max_price}
                    onChange={(e) => setDraft({ ...draft, max_price: e.target.value })}
                  />
                </div>

                <div className="field">
                  <label>Срок подачи с</label>
                  <input
                    type="date"
                    value={draft.deadline_from}
                    onChange={(e) => setDraft({ ...draft, deadline_from: e.target.value })}
                  />
                </div>

                <div className="field">
                  <label>Срок подачи по</label>
                  <input
                    type="date"
                    value={draft.deadline_to}
                    onChange={(e) => setDraft({ ...draft, deadline_to: e.target.value })}
                  />
                </div>

                <div className="field checks-block checks-row">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={draft.hide_outdated}
                      onChange={(e) => setDraft({ ...draft, hide_outdated: e.target.checked })}
                    />
                    Скрыть устаревшие
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={draft.hide_duplicates}
                      onChange={(e) => setDraft({ ...draft, hide_duplicates: e.target.checked })}
                    />
                    Без дублей
                  </label>
                  <span className="field-hint">Устаревшие — с прошедшим сроком; дубли — похожие лоты с разных площадок.</span>
                </div>
              </div>
            )}
          </form>

          {loading && !items.length ? (
            <div className="loading">Ищем тендеры…</div>
          ) : items.length === 0 ? (
            <div className="empty">
              <p className="empty-title">Ничего не найдено</p>
              <p className="empty-hint">
                Попробуйте убрать исключения, сменить OR на AND (или наоборот), расширить статус
                или сбросить фильтры к нише «реф + грузы».
              </p>
              <div className="hero-actions" style={{ justifyContent: "center", marginTop: "0.85rem" }}>
                <button className="btn btn-ghost" type="button" onClick={resetToNicheDefaults}>
                  Сбросить к нише
                </button>
                {draft.exclude.trim() ? (
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => setDraft((d) => ({ ...d, exclude: "" }))}
                  >
                    Убрать исключения
                  </button>
                ) : null}
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, match_any: !d.match_any }))}
                >
                  {draft.match_any ? "Включить AND" : "Включить OR"}
                </button>
              </div>
            </div>
          ) : (
            <div className="list">
              {items.map((t) => (
                <article key={t.id} className="tender" onClick={() => void openDetail(t)}>
                  <div>
                    <div className="tender-meta">
                      <span className="chip chip-accent">{sourceLabel(t.source, sources)}</span>
                      {t.relevance != null && t.relevance > 0 && <span className="chip chip-law">score {t.relevance}</span>}
                      {t.changed_at && <span className="chip">изменён</span>}
                      {t.watch_status && <span className="chip">{t.watch_status}</span>}
                      {t.status && <span className="chip">{t.status}</span>}
                      {t.region && <span className="chip">{t.region}</span>}
                      {t.okpd2 && <span className="chip">ОКПД {t.okpd2}</span>}
                    </div>
                    <h2>{t.title}</h2>
                    <p>{t.customer || "Заказчик не указан"} · до {formatDate(t.deadline_at)}</p>
                  </div>
                  <div className="tender-side">
                    <div className="price">{formatPrice(t.price, t.currency)}</div>
                    <span className="linkish">Карточка →</span>
                  </div>
                </article>
              ))}
            </div>
          )}

          <div className="pager">
            <button className="btn btn-ghost" disabled={page <= 1 || loading} onClick={() => { const n = page - 1; setPage(n); void load(n); }}>Назад</button>
            <span>Стр. {page} из {pages} · {total}</span>
            <button className="btn btn-ghost" disabled={page >= pages || loading} onClick={() => { const n = page + 1; setPage(n); void load(n); }}>Вперёд</button>
          </div>
        </>
      )}

      {selected && (
        <div className="drawer-backdrop" onClick={() => setSelected(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h2>{selected.title}</h2>
              <button className="btn btn-ghost" type="button" onClick={() => setSelected(null)}>Закрыть</button>
            </div>
            {detailLoading && <div className="loading">Подгружаем детали…</div>}
            <div className="drawer-grid">
              <div><span className="muted">Источник</span><div>{sourceLabel(selected.source, sources)}</div></div>
              <div><span className="muted">НМЦК</span><div>{formatPrice(selected.price)}</div></div>
              <div><span className="muted">Релевантность</span><div>{selected.relevance ?? 0}</div></div>
              <div><span className="muted">Срок</span><div>{formatDate(selected.deadline_at)}</div></div>
              <div><span className="muted">Заказчик</span><div>{selected.customer || "—"}{selected.customer_inn ? ` · ИНН ${selected.customer_inn}` : ""}</div></div>
              <div><span className="muted">ОКПД2 / способ</span><div>{selected.okpd2 || "—"} · {selected.method || "—"}</div></div>
            </div>
            {user && (
              <div className="hero-actions">
                <button className="btn btn-ghost" type="button" onClick={() => void setWatch(selected.id, "favorite").then(() => openDetail(selected))}>Избранное</button>
                <button className="btn btn-ghost" type="button" onClick={() => void setWatch(selected.id, "in_work").then(() => openDetail(selected))}>В работу</button>
                <button className="btn btn-ghost" type="button" onClick={() => void setWatch(selected.id, "done").then(() => openDetail(selected))}>Готово</button>
                <button className="btn btn-ghost" type="button" onClick={() => void checkTenderCompliance(selected.id).then(setCompliance)}>Проверить РНП/гарантии</button>
              </div>
            )}
            {compliance && (
              <section className="drawer-section">
                <h3>Комплаенс по ИНН {compliance.inn || "—"}</h3>
                <p>
                  РНП: {compliance.in_rnp ? "есть совпадения" : "не найден"} ·
                  Банк гарантий: {compliance.has_bank_guarantee ? "есть" : "нет данных"}
                </p>
                <p className="muted">{compliance.notes}</p>
              </section>
            )}
            {!!related.length && (
              <section className="drawer-section">
                <h3>Дубли / другие площадки</h3>
                <ul>
                  {related.map((r) => (
                    <li key={r.id}>
                      <button type="button" className="linkish" onClick={() => void openDetail(r)}>
                        {sourceLabel(r.source, sources)} · {formatPrice(r.price)} · {r.title.slice(0, 80)}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {!!changes.length && (
              <section className="drawer-section">
                <h3>История изменений</h3>
                <ul>
                  {changes.map((c) => (
                    <li key={c.id}>{c.field}: {c.old_value || "—"} → {c.new_value || "—"} ({formatDate(c.changed_at)})</li>
                  ))}
                </ul>
              </section>
            )}
            {!!selected.lots?.length && (
              <section className="drawer-section">
                <h3>Лоты</h3>
                <ul>{selected.lots.map((lot, i) => <li key={i}>{lot.name}{lot.price != null ? ` — ${formatPrice(lot.price)}` : ""}</li>)}</ul>
              </section>
            )}
            {!!selected.documents?.length && (
              <section className="drawer-section">
                <h3>Документы</h3>
                <ul>
                  {selected.documents.map((doc, i) => (
                    <li key={i}>{doc.url ? <a href={doc.url} target="_blank" rel="noreferrer">{doc.name}</a> : doc.name}</li>
                  ))}
                </ul>
              </section>
            )}
            <a className="btn btn-primary" href={selected.url} target="_blank" rel="noreferrer">Открыть на площадке</a>
          </aside>
        </div>
      )}
    </div>
  );
}
