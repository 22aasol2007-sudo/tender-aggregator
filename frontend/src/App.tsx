import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  Dashboard,
  Filters,
  FilterPreset,
  Profile,
  SavedSearch,
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
  emptyFilters,
  exportUrl,
  fetchChanges,
  fetchCustomer,
  fetchCustomers,
  fetchDashboard,
  fetchMe,
  fetchMethods,
  fetchMonitor,
  fetchPresets,
  fetchProfile,
  fetchRegions,
  fetchRelated,
  fetchSavedSearches,
  fetchSourceMetrics,
  fetchSources,
  fetchStats,
  fetchTender,
  fetchTenders,
  fetchWatches,
  filtersToPayload,
  formatDate,
  formatPrice,
  login,
  logout,
  presetToFilters,
  register,
  saveProfile,
  saveTelegram,
  setWatch,
  sourceLabel,
  triggerScrape,
  ComplianceResult,
  Customer,
  MonitorSnapshot,
  SourceMetric,
} from "./api";

type Tab = "feed" | "dashboard" | "watches" | "searches" | "profile" | "monitor" | "customers";

export default function App() {
  const [tab, setTab] = useState<Tab>("feed");
  const [user, setUser] = useState<User | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("admin@tender.local");
  const [password, setPassword] = useState("admin123");
  const [name, setName] = useState("Admin");

  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [draft, setDraft] = useState<Filters>(emptyFilters);
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
  const [compliance, setCompliance] = useState<ComplianceResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Tender | null>(null);
  const [changes, setChanges] = useState<TenderChange[]>([]);
  const [related, setRelated] = useState<Tender[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [searchName, setSearchName] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const me = await fetchMe();
        setUser(me);
      } catch {
        setUser(null);
      }
      try {
        const [src, pr, meth, reg, st] = await Promise.all([
          fetchSources(),
          fetchPresets(),
          fetchMethods(),
          fetchRegions(),
          fetchStats(),
        ]);
        setSources(src);
        setPresets(pr);
        setMethods(meth);
        setRegions(reg);
        setStats(st);
      } catch {
        /* ignore */
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
    setLoading(true);
    setError(null);
    try {
      const list = await fetchTenders(nextFilters, nextPage);
      setItems(list.items);
      setTotal(list.total);
      setPage(list.page);
      if (withStats) await refreshStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }

  // Single debounce: sync draft → filters then load (avoids double timers / stale match_any)
  const filterDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadAbort = useRef<AbortController | null>(null);

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
        const list = await fetchTenders(filters, 1);
        if (ac.signal.aborted) return;
        setItems(list.items);
        setTotal(list.total);
        setPage(list.page);
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
    }
    if (tab === "customers") {
      void fetchCustomers(customerQ).then(setCustomers).catch(() => setCustomers([]));
    }
  }, [tab, user, customerQ]);

  async function onAuth(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const u =
        authMode === "login"
          ? await login(email, password)
          : await register(email, password, name);
      setUser(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
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
          <p className="muted">По умолчанию: admin@tender.local / admin123</p>
          {authMode === "register" && (
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя" />
          )}
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
          />
          <div className="hero-actions">
            <button className="btn btn-primary" type="submit">
              {authMode === "login" ? "Войти" : "Создать аккаунт"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
            >
              {authMode === "login" ? "Регистрация" : "У меня есть аккаунт"}
            </button>
          </div>
        </form>
      )}

      {error && <div className="error">{error}</div>}

      {tab === "monitor" && (
        <section className="panel">
          <h3>Качество парсеров и тишина источников</h3>
          {monitor && (
            <p className="muted">
              Проверка: {formatDate(monitor.checked_at)} · порог тишины {monitor.silence_minutes} мин ·
              проблемных: {monitor.unhealthy_count}
              {monitor.alerts.length > 0 ? ` · алертов: ${monitor.alerts.length}` : ""}
            </p>
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
                    await createSavedSearch(searchName.trim(), filtersToPayload(filters), true);
                    setSearchName("");
                    setSearches(await fetchSavedSearches());
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
                          void ackSavedSearch(s.id).then(async () => setSearches(await fetchSavedSearches()));
                        }}
                      >
                        Открыть
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={async () => {
                          await deleteSavedSearch(s.id);
                          setSearches(await fetchSavedSearches());
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

          <div className="presets">
            {presets.map((p) => (
              <button key={p.id} type="button" className="preset-chip" onClick={() => { const n = presetToFilters(p); setDraft(n); setFilters(n); }}>
                {p.name}
              </button>
            ))}
            <a className="preset-chip ghost" href={exportUrl(filters, "csv")}>CSV</a>
            <a className="preset-chip ghost" href={exportUrl(filters, "xlsx")}>Excel</a>
          </div>

          <form
            className="filters filters-wide"
            onSubmit={(e) => {
              e.preventDefault();
              setPage(1);
              setFilters(draft);
            }}
          >
            <div className="field grow">
              <label>Ключевые слова</label>
              <input
                value={draft.q}
                onChange={(e) => setDraft({ ...draft, q: e.target.value })}
                placeholder="рефрижератор, перевозка грузов — через запятую"
              />
            </div>
            <div className="field grow">
              <label>Исключить слова</label>
              <input
                value={draft.exclude}
                onChange={(e) => setDraft({ ...draft, exclude: e.target.value })}
                placeholder="ПО, канцелярия — убрать из выдачи"
              />
            </div>
            <div className="field">
              <label>Источник</label>
              <select value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
                <option value="">Все</option>
                {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
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
              <label>Регион</label>
              <input list="regions" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })} />
              <datalist id="regions">{regions.map((r) => <option key={r} value={r} />)}</datalist>
            </div>
            <div className="field">
              <label>Способ</label>
              <input list="methods" value={draft.method} onChange={(e) => setDraft({ ...draft, method: e.target.value })} />
              <datalist id="methods">{methods.map((m) => <option key={m} value={m} />)}</datalist>
            </div>
            <div className="field">
              <label>ОКПД2</label>
              <input value={draft.okpd2} onChange={(e) => setDraft({ ...draft, okpd2: e.target.value })} />
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
              <label>НМЦК от</label>
              <input type="number" value={draft.min_price} onChange={(e) => setDraft({ ...draft, min_price: e.target.value })} />
            </div>
            <div className="field">
              <label>НМЦК до</label>
              <input type="number" value={draft.max_price} onChange={(e) => setDraft({ ...draft, max_price: e.target.value })} />
            </div>
            <div className="field checks">
              <label className="check"><input type="checkbox" checked={draft.match_any} onChange={(e) => setDraft({ ...draft, match_any: e.target.checked })} />Любое из слов (OR)</label>
              <label className="check"><input type="checkbox" checked={draft.hide_outdated} onChange={(e) => setDraft({ ...draft, hide_outdated: e.target.checked })} />Скрыть устаревшие</label>
              <label className="check"><input type="checkbox" checked={draft.hide_duplicates} onChange={(e) => setDraft({ ...draft, hide_duplicates: e.target.checked })} />Без дублей</label>
            </div>
            <div className="field" style={{ justifyContent: "flex-end" }}>
              <label>&nbsp;</label>
              <button className="btn btn-primary" type="submit">Найти</button>
            </div>
          </form>

          {loading && !items.length ? (
            <div className="loading">Загрузка…</div>
          ) : items.length === 0 ? (
            <div className="empty">Ничего не найдено</div>
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
