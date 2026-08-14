const $ = (id) => document.getElementById(id);
let lastHealthAt = 0;
let lastTgDown = false;
let lastMuted = [];
let activeChannel = "all";
let parseSummaryDismissed = false;

const TG_SOURCES = new Set(["telegram", "tg_public"]);
const MAX_SOURCES = new Set(["max"]);

function sourceFamily(source) {
  const s = String(source || "").toLowerCase();
  if (TG_SOURCES.has(s)) return "tg";
  if (MAX_SOURCES.has(s)) return "max";
  return "sites";
}

function sourceLabel(source) {
  const s = String(source || "").toLowerCase();
  if (s === "telegram" || s === "tg_public") return "Telegram";
  if (s === "max") return "MAX";
  return source || "сайт";
}

function fmtPosted(item) {
  let t = Number(item.created_at || item.scraped_at || 0);
  if (!t) return "";
  if (t > 1e12) t = t / 1000; // ms → sec
  const d = new Date(t * 1000);
  if (Number.isNaN(d.getTime())) return "";
  // Always show Moscow wall-clock so TG/boards match carrier expectation
  const parts = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type) => (parts.find((p) => p.type === type) || {}).value || "";
  const year = get("year");
  const yShort = year && year !== String(new Date().getFullYear()) ? `.${year}` : "";
  return `${get("day")}.${get("month")}${yShort} ${get("hour")}:${get("minute")}`;
}

function metaContent(name) {
  const el = document.querySelector(`meta[name="${name}"]`);
  return el ? (el.getAttribute("content") || "") : "";
}

function writeToken() {
  const injected = metaContent("hub-write-token");
  if (injected) {
    try { localStorage.setItem("hub_write_token", injected); } catch {}
    return injected;
  }
  try { return localStorage.getItem("hub_write_token") || ""; } catch { return ""; }
}

function ensureWriteToken() {
  let t = writeToken();
  if (t) return t;
  if (metaContent("write-token-required") !== "1") return "";
  t = window.prompt("Токен записи (HUB_WRITE_TOKEN):") || "";
  if (t) {
    try { localStorage.setItem("hub_write_token", t); } catch {}
  }
  return t;
}

async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = { ...(opts.headers || {}) };
  if (method !== "GET" && method !== "HEAD") {
    const tok = ensureWriteToken();
    if (tok) headers["X-Hub-Token"] = tok;
  }
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401 && method !== "GET") {
    try { localStorage.removeItem("hub_write_token"); } catch {}
    const again = window.prompt("Нужен токен записи. Вставьте HUB_WRITE_TOKEN:") || "";
    if (again) {
      try { localStorage.setItem("hub_write_token", again); } catch {}
      headers["X-Hub-Token"] = again;
      const r2 = await fetch(path, { ...opts, headers });
      if (!r2.ok) throw new Error(await r2.text());
      return r2.json();
    }
  }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function routeText(item) {
  const a = (item.from_city || "").trim();
  const b = (item.to_city || "").trim();
  let base = "";
  if (a && b) base = `${a} → ${b}`;
  else if (a || b) base = `${a || "?"} → ${b || "?"}`;
  else {
    const title = (item.title || "").trim();
    if (title && !/^\?\s*→\s*\?$/.test(title)) base = title;
    else base = "Маршрут не указан";
  }
  const km = Number(item.route_km);
  if (Number.isFinite(km) && km > 0) {
    return `${base} · ${Math.round(km)} км`;
  }
  return base;
}

function parseList(val) {
  if (Array.isArray(val)) return val;
  if (typeof val === "string") {
    try {
      const j = JSON.parse(val);
      return Array.isArray(j) ? j : [];
    } catch {
      return val ? [val] : [];
    }
  }
  return [];
}

function allContacts(item) {
  const phones = parseList(item.phones).filter(Boolean);
  const contacts = parseList(item.contacts).filter(Boolean);
  const out = [];
  for (const p of phones) out.push({ kind: "phone", href: `tel:${p}`, label: p });
  for (const c of contacts) {
    const handle = String(c).replace(/^@/, "");
    out.push({ kind: "tg", href: `https://t.me/${handle}`, label: `@${handle}` });
  }
  if (item.url) out.push({ kind: "url", href: item.url, label: "Открыть" });
  return out;
}

function muteKey(item) {
  if (item.from_city && item.to_city) return `${item.from_city}-${item.to_city}`;
  return item.from_city || item.to_city || "";
}

function ageSec(item) {
  const t = Number(item.created_at || item.scraped_at || 0);
  return t ? Math.max(0, Date.now() / 1000 - t) : 1e9;
}

function groupOf(item) {
  const age = ageSec(item);
  if (age <= 1800 && Number(item.score || 0) >= 70) return "hot";
  const d = new Date((item.scraped_at || item.created_at || 0) * 1000);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "today";
  return "rest";
}

function setStatus(key, mode) {
  const el = document.querySelector(`.st[data-k="${key}"]`);
  if (!el) return;
  el.classList.remove("on", "warn", "off");
  el.classList.add(mode);
}

function fmtAgo(sec) {
  if (!Number.isFinite(sec) || sec < 0) return "";
  if (sec < 10) return "только что";
  if (sec < 60) return `${Math.round(sec)}с назад`;
  if (sec < 3600) return `${Math.round(sec / 60)}м назад`;
  return `${Math.round(sec / 3600)}ч назад`;
}

function renderMuteBar(muted) {
  lastMuted = Array.isArray(muted) ? muted : [];
  const bar = $("muteBar");
  const list = $("muteList");
  if (!bar || !list) return;
  if (!lastMuted.length) {
    bar.hidden = true;
    list.innerHTML = "";
    return;
  }
  bar.hidden = false;
  list.innerHTML = lastMuted.map((d) =>
    `<button type="button" class="mute-chip" data-dir="${esc(d)}">${esc(d)} ×</button>`
  ).join("");
  list.querySelectorAll(".mute-chip").forEach((btn) => {
    btn.onclick = async () => {
      const direction = btn.dataset.dir;
      await api(`/api/mute?direction=${encodeURIComponent(direction)}`, { method: "DELETE" });
      await loadList();
    };
  });
}

function render(items, meta) {
  const list = $("list");
  renderMuteBar(meta && meta.muted_directions);

  if (!items.length) {
    const outside = meta && meta.outside_corridor;
    const reasons = (meta && meta.filter_reasons) || [];
    const tip = outside && outside.message
      ? outside.message
      : (reasons.length ? reasons.join(" · ") : "Снимите узкие фильтры или обновите источники.");
    const tgCta = lastTgDown
      ? `<a class="btn" href="/tg-login">Войти в Telegram</a>`
      : "";
    const outsideBtn = outside && outside.count
      ? `<button type="button" class="btn" id="emptyOutside">Показать вне радиуса (${outside.count})</button>`
      : "";
    list.innerHTML = `<div class="empty">
      <div>Ничего не найдено</div>
      <div style="margin-top:8px">${esc(tip)}</div>
      <div class="empty-actions">
        ${outsideBtn}
        ${tgCta}
        <button type="button" class="btn ghost" id="emptyReset">Сбросить фильтры</button>
      </div>
    </div>`;
    const btn = $("emptyReset");
    if (btn) btn.onclick = () => { resetFilters(); loadList().catch(alert); };
    const outBtn = $("emptyOutside");
    if (outBtn) {
      outBtn.onclick = () => {
        if ($("geoCorridor")) $("geoCorridor").checked = false;
        loadList().catch(alert);
      };
    }
    return;
  }

  maybeNotifyHot(items);

  const groups = { hot: [], today: [], rest: [] };
  for (const it of items) groups[groupOf(it)].push(it);
  const labels = { hot: "Горячие", today: "Сегодня", rest: "Остальные" };
  let html = "";
  for (const key of ["hot", "today", "rest"]) {
    if (!groups[key].length) continue;
    html += `<div class="group-title">${labels[key]} · ${groups[key].length}</div>`;
    html += groups[key].map(cardHtml).join("");
  }
  list.innerHTML = html;

  list.querySelectorAll(".show").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("dlgBody").textContent = decodeURIComponent(btn.dataset.full || "");
      $("dlg").showModal();
    });
  });
  list.querySelectorAll(".mute").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const direction = btn.dataset.dir;
      if (!direction) return;
      await api("/api/mute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction }),
      });
      await loadList();
    });
  });
  list.querySelectorAll(".copy-contact").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const val = btn.dataset.copy || "";
      try {
        await navigator.clipboard.writeText(val);
        btn.textContent = "Скопировано";
        setTimeout(() => { btn.textContent = "Скопировать"; }, 1200);
      } catch {
        alert(val);
      }
    });
  });
}

function cardHtml(item) {
  const fresh = ageSec(item) <= 300;
  const contacts = allContacts(item);
  const facts = [];
  if (item.tonnage != null) facts.push(`<span><b>${esc(item.tonnage)}</b> т</span>`);
  if (item.volume_m3 != null) facts.push(`<span><b>${esc(item.volume_m3)}</b> м³</span>`);
  if (item.body_type) facts.push(`<span>${esc(item.body_type)}</span>`);
  if (item.price) facts.push(`<span><b>${esc(item.price)}</b></span>`);
  if (item.price_per_km != null) {
    const ppk = Number(item.price_per_km);
    facts.push(`<span><b>${esc(ppk.toLocaleString("ru-RU", { maximumFractionDigits: 0 }))}</b> ₽/км</span>`);
  }
  // route_km already shown in route line; keep compact fact only if route line had no cities
  if (item.route_km != null && !(item.from_city && item.to_city)) {
    facts.push(`<span>${esc(Math.round(Number(item.route_km)))} км</span>`);
  }
  if (item.load_date) facts.push(`<span>${esc(item.load_date)}</span>`);

  const meta = [];
  meta.push(`<span class="source-tag">${esc(sourceLabel(item.source))}</span>`);
  if (Array.isArray(item.sources) && item.sources.length > 1) {
    const names = item.sources.map((s) => sourceLabel(s.source)).filter(Boolean);
    const uniq = [...new Set(names)];
    if (uniq.length > 1) meta.push(`<span class="source-tag multi">${esc(uniq.join(" + "))}</span>`);
  }
  const posted = fmtPosted(item);
  if (posted) meta.push(`<span class="posted-at" title="Дата публикации на источнике">${esc(posted)}</span>`);
  if (item.km_from != null) meta.push(`погр. ${Math.round(item.km_from)} км`);
  if (item.km_to != null) meta.push(`выгр. ${Math.round(item.km_to)} км`);

  const why = Array.isArray(item.why) && item.why.length
    ? `<div class="why">${esc(item.why.join(" · "))}</div>`
    : "";
  const mk = muteKey(item);
  const score = Math.max(0, Math.min(100, Number(item.score || 0)));
  const family = sourceFamily(item.source);

  const primary = contacts[0];
  const callBtn = primary && primary.kind === "phone"
    ? `<a class="cta call" href="${esc(primary.href)}">Позвонить</a>`
    : primary
      ? `<a class="cta call" href="${esc(primary.href)}" target="_blank" rel="noopener">${esc(primary.kind === "tg" ? "Написать" : "Открыть")}</a>`
      : `<button type="button" class="cta call show" data-full="${encodeURIComponent(item.body || "")}">Открыть</button>`;
  const copyVal = primary ? primary.label.replace(/^@/, "") : "";
  const copyBtn = copyVal
    ? `<button type="button" class="cta copy copy-contact" data-copy="${esc(copyVal)}">Скопировать</button>`
    : "";

  const contactRows = contacts.map((c) =>
    `<a class="contact-row" href="${esc(c.href)}" ${c.kind !== "phone" ? 'target="_blank" rel="noopener"' : ""}>${esc(c.label)}</a>`
  ).join("");

  return `<article class="card src-${family}${fresh ? " fresh" : ""}">
    <div class="card-main">
      <div class="route">${esc(routeText(item))}</div>
      <div class="facts">${facts.join("") || "<span>детали в тексте</span>"}</div>
      <div class="meta-row">${meta.join('<span>·</span>')}</div>
      ${why}
      ${contactRows ? `<div class="contacts">${contactRows}</div>` : ""}
    </div>
    <div class="actions">
      <div class="score-bar" title="Скор ${score}"><span style="width:${score}%"></span></div>
      <div class="cta-row">${callBtn}${copyBtn}</div>
      <button type="button" class="ghost show" data-full="${encodeURIComponent(item.body || "")}">Текст</button>
      ${mk ? `<button type="button" class="ghost mute" data-dir="${esc(mk)}">Скрыть</button>` : ""}
    </div>
  </article>`;
}

async function refreshHealth() {
  try {
    const h = await api("/api/health");
    lastHealthAt = Date.now();
    const statuses = h.statuses || {};
    setStatus("tg", statuses.tg || (h.tg ? "on" : "off"));
    setStatus("max", statuses.max || (h.max ? "on" : "off"));
    setStatus("sites", statuses.sites || "on");
    const ago = h.updated_ago_sec;
    $("updatedAgo").textContent = ago != null ? fmtAgo(ago) : "сейчас";
    lastTgDown = !!(h.tg_down || h.tg_need_login || statuses.tg === "off");

    showParseSummary(h.coverage);

    const banner = $("banner");
    if (h.hints && h.hints.length) {
      banner.hidden = false;
      const text = h.hints.join(" ");
      if (lastTgDown || text.includes("/tg-login")) {
        banner.innerHTML = `${esc(text)} — <a class="banner-cta" href="/tg-login">Войти в Telegram</a>`;
      } else {
        banner.textContent = text;
      }
    } else {
      banner.hidden = true;
      banner.textContent = "";
    }
  } catch {
    setStatus("tg", "off");
    setStatus("max", "off");
    setStatus("sites", "warn");
    $("updatedAgo").textContent = "offline";
    lastTgDown = true;
  }
}

function ratioLabel(ok, total) {
  const o = Number(ok) || 0;
  const t = Number(total) || 0;
  if (t <= 0) return { text: "—", pct: "" };
  const pct = Math.round((100 * o) / t);
  return { text: `${o}/${t}`, pct: `${pct}%` };
}

function showParseSummary(coverage) {
  const box = $("parseSummary");
  if (!box || !coverage || parseSummaryDismissed) return;
  const chats = coverage.chats || {};
  const sites = coverage.sites || {};
  const c = ratioLabel(chats.ok, chats.total);
  const s = ratioLabel(sites.ok, sites.total);
  $("sumChats").textContent = c.text;
  $("sumChatsPct").textContent = c.pct;
  $("sumSites").textContent = s.text;
  $("sumSitesPct").textContent = s.pct;
  const bits = [];
  if (chats.tg_total) bits.push(`TG ${chats.tg_ok || 0}/${chats.tg_total}`);
  if (chats.max_total) bits.push(`MAX ${chats.max_ok || 0}/${chats.max_total}`);
  const detail = $("sumDetail");
  if (detail)   detail.textContent = bits.join(" · ");
  box.hidden = false;
}

function numOrEmpty(id) {
  const el = $(id);
  if (!el) return "";
  const v = String(el.value || "").trim();
  return v;
}

function currentParams() {
  const params = new URLSearchParams();
  const q = $("q").value.trim();
  const body = $("body").value;
  const frm = $("from").value.trim();
  const to = $("to").value.trim();
  const minScore = $("minScore").value || "40";
  if (q) params.set("q", q);
  if (activeChannel && activeChannel !== "all") params.set("channel", activeChannel);
  if (body) params.set("body_type", body);
  if (frm) params.set("from", frm);
  if (to) params.set("to", to);
  if ($("exactFrom") && $("exactFrom").checked) params.set("exact_from", "true");
  if ($("exactTo") && $("exactTo").checked) params.set("exact_to", "true");
  const tMin = numOrEmpty("tonnageMin");
  const tMax = numOrEmpty("tonnageMax");
  const vMin = numOrEmpty("volumeMin");
  const vMax = numOrEmpty("volumeMax");
  const ppk = numOrEmpty("ppkMin");
  const price = numOrEmpty("priceMin");
  const rMin = numOrEmpty("routeKmMin");
  const rMax = numOrEmpty("routeKmMax");
  if (tMin) params.set("tonnage_min", tMin);
  if (tMax) params.set("tonnage_max", tMax);
  if (vMin) params.set("volume_min", vMin);
  if (vMax) params.set("volume_max", vMax);
  if (ppk) params.set("ppk_min", ppk);
  if (price) params.set("price_min", price);
  if (rMin) params.set("route_km_min", rMin);
  if (rMax) params.set("route_km_max", rMax);
  const fresh = $("freshness") ? $("freshness").value : "";
  if (fresh) params.set("freshness_hours", fresh);
  const loadDate = $("loadDateMode") ? $("loadDateMode").value : "any";
  if (loadDate && loadDate !== "any") params.set("load_date_mode", loadDate);
  const loading = $("loading") ? $("loading").value : "any";
  if (loading && loading !== "any") params.set("loading", loading);
  const cargoMode = $("cargoMode") ? $("cargoMode").value : "any";
  if (cargoMode && cargoMode !== "any") params.set("cargo_mode", cargoMode);
  const payment = $("payment") ? $("payment").value : "any";
  if (payment && payment !== "any") params.set("payment", payment);
  params.set("min_score", minScore);
  params.set("sort", $("sort").value || "date");
  params.set("shipper_only", $("shipperOnly").checked ? "true" : "false");
  params.set("geo", ($("geoCorridor") ? $("geoCorridor").checked : true) ? "true" : "false");
  if ($("reefer").checked) params.set("reefer", "true");
  if ($("hotOnly").checked) params.set("hot", "true");
  params.set("limit", "300");
  return params;
}

async function loadList() {
  const params = currentParams();
  const data = await api(`/api/loads?${params}`);
  const count = data.count || 0;
  const explain = data.rank_explain || "";
  $("meta").textContent = explain
    ? `Показано: ${count}. ${explain}`
    : `Показано: ${count}`;
  render(data.items || [], data);
}

function setChannel(channel) {
  activeChannel = channel || "all";
  document.querySelectorAll(".tab").forEach((btn) => {
    const on = btn.dataset.channel === activeChannel;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
}

function resetFilters() {
  $("q").value = "";
  $("from").value = "";
  $("to").value = "";
  $("body").value = "";
  $("sort").value = "date";
  $("shipperOnly").checked = true;
  $("reefer").checked = false;
  $("hotOnly").checked = false;
  $("minScore").value = "45";
  if ($("geoCorridor")) $("geoCorridor").checked = true;
  if ($("exactFrom")) $("exactFrom").checked = false;
  if ($("exactTo")) $("exactTo").checked = false;
  ["tonnageMin", "tonnageMax", "volumeMin", "volumeMax", "ppkMin", "priceMin", "routeKmMin", "routeKmMax"].forEach((id) => {
    if ($(id)) $(id).value = "";
  });
  if ($("freshness")) $("freshness").value = "";
  if ($("loadDateMode")) $("loadDateMode").value = "any";
  if ($("loading")) $("loading").value = "any";
  if ($("cargoMode")) $("cargoMode").value = "any";
  if ($("payment")) $("payment").value = "any";
  setChannel("all");
}

async function loadProfile() {
  try {
    const p = await api("/api/profile");
    const t = p.truck_profile || {};
    $("pBase").value = t.base || "";
    $("pBody").value = t.body || "";
    $("pTonnage").value = t.tonnage ?? "";
    $("pRadius").value = t.radius ?? "";
    $("pRadiusFar").value = t.radius_far ?? t.far_radius ?? "";
    $("pBackhaul").checked = !!t.backhaul;
    if ($("pDiesel")) $("pDiesel").value = t.diesel_rub_per_l ?? "";
    if ($("pFuelL")) $("pFuelL").value = t.fuel_l_per_100km ?? "";
    if ($("pDriver")) $("pDriver").value = t.driver_day_rub ?? "";
    if ($("pTax")) $("pTax").value = t.tax_pct != null ? Math.round(Number(t.tax_pct) * (Number(t.tax_pct) <= 1 ? 100 : 1)) : "";
    if ($("pAmort")) $("pAmort").value = t.amortization_pct != null ? Math.round(Number(t.amortization_pct) * (Number(t.amortization_pct) <= 1 ? 100 : 1)) : "";
    if ($("pTargetMin")) $("pTargetMin").value = t.target_net_min ?? "";
    if ($("pTargetMax")) $("pTargetMax").value = t.target_net_max ?? "";
    renderMuteBar(p.muted_directions || []);
  } catch (e) {
    console.warn(e);
  }
}

async function saveProfile(extra = {}) {
  const body = {
    base: $("pBase").value.trim() || null,
    body: $("pBody").value || null,
    tonnage: $("pTonnage").value ? Number($("pTonnage").value) : null,
    radius: $("pRadius").value ? Number($("pRadius").value) : null,
    radius_far: $("pRadiusFar").value ? Number($("pRadiusFar").value) : null,
    backhaul: $("pBackhaul").checked,
    diesel_rub_per_l: $("pDiesel")?.value ? Number($("pDiesel").value) : null,
    fuel_l_per_100km: $("pFuelL")?.value ? Number($("pFuelL").value) : null,
    driver_day_rub: $("pDriver")?.value ? Number($("pDriver").value) : null,
    tax_pct: $("pTax")?.value ? Number($("pTax").value) / 100 : null,
    amortization_pct: $("pAmort")?.value ? Number($("pAmort").value) / 100 : null,
    target_net_min: $("pTargetMin")?.value ? Number($("pTargetMin").value) : null,
    target_net_max: $("pTargetMax")?.value ? Number($("pTargetMax").value) : null,
    ...extra,
  };
  const res = await api("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const km = res.km_recompute;
  $("meta").textContent = km && km.updated
    ? `Профиль сохранён · коридор пересчитан от «${km.base}» (${km.updated} заявок)`
    : "Профиль сохранён";
}

const PRESETS = {
  "reefer-msk": { base: "москва", body: "reefer", tonnage: null, radius: 150, radius_far: 1500, backhaul: false },
  "tent-20": { base: "москва", body: "tent", tonnage: 20, radius: 150, radius_far: 1500, backhaul: false },
  "box-city": { base: "москва", body: "box", tonnage: 3, radius: 80, radius_far: 250, backhaul: false },
};

$("btnApply").addEventListener("click", () => loadList().catch(alert));
$("btnReset").addEventListener("click", () => { resetFilters(); loadList().catch(alert); });
$("btnSaveProfile").addEventListener("click", async () => {
  await saveProfile();
  await loadList();
});
$("btnMore").addEventListener("click", () => {
  const el = $("moreFilters");
  el.hidden = !el.hidden;
  $("btnMore").textContent = el.hidden ? "Ещё параметры" : "Скрыть параметры";
});
const swapBtn = $("btnSwapRoute");
if (swapBtn) {
  swapBtn.addEventListener("click", () => {
    const a = $("from").value;
    $("from").value = $("to").value;
    $("to").value = a;
    const ea = $("exactFrom") ? $("exactFrom").checked : false;
    if ($("exactFrom") && $("exactTo")) {
      $("exactFrom").checked = $("exactTo").checked;
      $("exactTo").checked = ea;
    }
    loadList().catch(alert);
  });
}
document.querySelectorAll(".tab[data-channel]").forEach((btn) => {
  btn.addEventListener("click", () => {
    setChannel(btn.dataset.channel || "all");
    loadList().catch(alert);
  });
});

function setAppView(view) {
  const feed = view !== "analyze";
  const feedSec = $("viewFeed");
  const analyzeSec = $("viewAnalyze");
  const feedMain = $("feedMain");
  if (feedSec) feedSec.hidden = !feed;
  if (feedMain) feedMain.hidden = !feed;
  if (analyzeSec) analyzeSec.hidden = feed;
  document.querySelectorAll(".mode-tabs .tab").forEach((btn) => {
    const on = (btn.dataset.view || "feed") === view;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (!feed && $("aBase") && !$("aBase").value && $("pBase")) {
    $("aBase").value = $("pBase").value || "москва";
  }
}

document.querySelectorAll(".mode-tabs .tab").forEach((btn) => {
  btn.addEventListener("click", () => setAppView(btn.dataset.view || "feed"));
});

function fmtRub(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `${Math.round(Number(n)).toLocaleString("ru-RU")} ₽`;
}

function riskClass(risk) {
  if (risk === "низкий") return "risk-low";
  if (risk === "средний") return "risk-mid";
  return "risk-high";
}

function verdictToneClass(tone) {
  if (tone === "take") return "take";
  if (tone === "raise" || tone === "propose") return "raise";
  if (tone === "skip") return "skip";
  return "muted";
}

function renderWaterfall(wf) {
  if (!wf || !wf.steps) return "";
  const rows = wf.steps.map((s) => {
    const isNet = s.key === "net";
    return `<div class="wf-row ${isNet ? "wf-net" : ""}">
      <span class="wf-sign">${esc(s.sign || "")}</span>
      <span class="wf-label">${esc(s.label)}</span>
      <span class="wf-val">${fmtRub(Math.abs(s.rub))}${s.rub < 0 ? "" : ""}</span>
    </div>`;
  }).join("");
  return `<div class="waterfall">${rows}</div>`;
}

function fillAnalyzeFormFromData(data, extracted = {}) {
  if ($("aFrom") && (data.from_city || extracted.from_city)) {
    $("aFrom").value = data.from_city || extracted.from_city || "";
  }
  if ($("aDest") && (data.destination || extracted.to_city)) {
    $("aDest").value = data.destination || extracted.to_city || "";
  }
  if ($("aBase") && data.base) $("aBase").value = data.base;
  if ($("aKm") && (data.route_km != null || extracted.route_km != null)) {
    $("aKm").value = Math.round(Number(data.route_km ?? extracted.route_km));
  }
  const offer = (data.pricing && data.pricing.offer && data.pricing.offer.offer_rub)
    || extracted.price_rub;
  if ($("aOffer") && offer != null) $("aOffer").value = Math.round(Number(offer));
}

function renderAnalyzeResult(data, extra = {}) {
  const bh = data.backhaul || {};
  const pr = data.pricing || {};
  const live = data.live_external || {};
  const verdict = data.verdict || extra.advice || {};
  const wf = data.waterfall || (pr.offer && pr.offer.waterfall) || (data.economics && data.economics.waterfall);
  const scenarios = data.scenarios || (data.economics && data.economics.scenarios) || {};
  const market = data.market || {};
  const offer = pr.offer || {};

  const liveFails = (live.sources || []).filter((s) => !s.ok);
  const liveOk = (live.sources || []).filter((s) => s.ok);
  const liveSummary = liveOk.length
    ? liveOk.map((s) => `${s.name}: ${s.count ?? 0}`).join(" · ")
    : "нет live-данных";
  const liveDetails = liveFails.map((s) =>
    `<li><strong>${esc(s.name || "?")}</strong>: ${esc(s.note || s.error || "ошибка")}</li>`
  ).join("");

  const nearbyRows = (bh.nearby_cities || []).slice(0, 5).map((r) =>
    `<tr><td>${esc(r.city)}</td><td>${r.backhaul_n}</td><td>${r.avg_ppk ?? "—"}</td></tr>`
  ).join("");

  const propose = verdict.propose_rub ?? pr.suggested_min_total_rub;
  const light = verdictToneClass(verdict.tone || verdict.action);
  const hubNote = data.destination_hub && data.destination_hub !== data.destination
    ? ` · хаб ${esc(data.destination_hub)}`
    : "";
  const kmSrc = data.km_source === "manual" ? "ручн." : (data.km_source === "geo" ? "гео" : "?");
  const bhBreak = `лента ${bh.count_feed ?? 0}`
    + (bh.count_external ? ` + live ${bh.count_external}` : "")
    + ` = ${bh.count ?? 0}`;

  const scBh = scenarios.with_backhaul || {};
  const scEmpty = scenarios.empty_return || {};

  const marketHtml = renderMarketScale(market);

  let offerBlock = "";
  if (offer.offer_rub != null) {
    const vs = offer.vs_hurdle_rub;
    const vsTxt = vs == null ? "" : (vs >= 0 ? `+${fmtRub(vs)} к порогу` : `${fmtRub(vs)} к порогу`);
    offerBlock = `<div class="offer-summary">
      <div>Ставка <b>${fmtRub(offer.offer_rub)}</b>${offer.offer_ppk != null ? ` · ${offer.offer_ppk} ₽/км` : ""}</div>
      <div class="muted">чистыми ~${fmtRub(offer.expected_net_rub)} · ${esc(offer.verdict || "")}${vsTxt ? ` · ${vsTxt}` : ""}</div>
      ${propose != null ? `<div class="muted">порог «от» ${fmtRub(propose)}</div>` : ""}
    </div>`;
  }

  const notes = (data.notes || []).map((n) => `<li>${esc(n)}</li>`).join("");

  fillAnalyzeFormFromData(data, extra.extracted || {});

  $("analyzeOut").hidden = false;
  $("analyzeOut").innerHTML = `
    <div class="verdict-hero ${esc(light)}">
      <div class="verdict-light">${esc(verdict.label || "—")}</div>
      <div class="verdict-num">${propose != null ? `от ${fmtRub(propose)}` : "нет ставки"}</div>
      <div class="verdict-sub">${esc(verdict.text || "")}</div>
      ${offerBlock}
      <div class="muted">${esc(data.from_city || data.base)} → ${esc(data.destination)}${hubNote}
        · ${data.route_km ? `${data.route_km} км (${kmSrc})` : "км?"}
        · обратка ${bhBreak} · p≈${bh.p_find ?? "—"} · риск ${esc(bh.risk || "—")}</div>
      ${marketHtml}
    </div>

    <div class="analyze-card">
      <div class="ati-label">Водопад ставки</div>
      ${renderWaterfall(wf) || `<p class="muted">Нет данных для водопада</p>`}
    </div>

    <div class="scenario-grid">
      <div class="analyze-card scenario-card">
        <div class="ati-label">${esc(scBh.label || "С обраткой")}</div>
        <div class="analyze-big">${fmtRub(scBh.suggest_min_rub)}</div>
        <div class="muted">ориентир ${fmtRub(scBh.suggest_mid_rub)} · ${scBh.ppk ?? "—"} ₽/км</div>
        <div class="muted">затраты ${fmtRub(scBh.costs_rub)} · ${scBh.hours ?? "—"} ч / ${scBh.days ?? "—"} сут</div>
      </div>
      <div class="analyze-card scenario-card">
        <div class="ati-label">${esc(scEmpty.label || "Без обратки")}</div>
        <div class="analyze-big">${fmtRub(scEmpty.suggest_min_rub)}</div>
        <div class="muted">ориентир ${fmtRub(scEmpty.suggest_mid_rub)} · ${scEmpty.ppk ?? "—"} ₽/км</div>
        <div class="muted">затраты ${fmtRub(scEmpty.costs_rub)} · ${scEmpty.hours ?? "—"} ч / ${scEmpty.days ?? "—"} сут</div>
      </div>
    </div>

    <div class="analyze-card">
      <div class="ati-label">Топ-5 обратки в ${bh.radius_km ?? 100} км</div>
      <table class="analyze-table"><thead><tr><th>Город</th><th>N</th><th>₽/км</th></tr></thead>
      <tbody>${nearbyRows || "<tr><td colspan=3>нет данных за 7 суток</td></tr>"}</tbody></table>
      <div class="muted" style="margin-top:8px">Live: ${esc(liveSummary)}${live.cached ? " (кэш)" : ""}</div>
      ${liveDetails ? `<details class="live-details"><summary>Подробности live / ошибки</summary><ul class="analyze-sources">${liveDetails}</ul></details>` : ""}
    </div>

    ${notes ? `<ul class="analyze-notes">${notes}</ul>` : ""}
  `;
}

async function runAnalyze() {
  const dest = ($("aDest").value || "").trim();
  if (!dest) {
    alert("Укажите город выгрузки");
    return;
  }
  const base = ($("aBase").value || $("pBase").value || "москва").trim();
  const fromCity = ($("aFrom") && $("aFrom").value || "").trim();
  const offer = ($("aOffer").value || "").trim();
  const km = ($("aKm") && $("aKm").value || "").trim();
  const live = $("aLive") ? $("aLive").checked : true;
  const params = new URLSearchParams({
    destination: dest,
    base,
    live: live ? "true" : "false",
  });
  if (fromCity) params.set("from_city", fromCity);
  if (offer) params.set("offer_rub", offer);
  if (km) params.set("route_km", km);
  const ton = ($("pTonnage").value || "").trim();
  const body = ($("pBody").value || "").trim();
  if (ton) params.set("tonnage", ton);
  if (body) params.set("body", body);

  $("btnAnalyze").disabled = true;
  $("analyzeOut").hidden = false;
  $("analyzeOut").innerHTML = `<p class="analyze-loading">Считаем…</p>`;
  try {
    const data = await api(`/api/analyze/route?${params}`);
    if (!data.ok) {
      $("analyzeOut").innerHTML = `<p class="analyze-err">${esc(data.error || "Ошибка")}</p>`;
      return;
    }
    renderAnalyzeResult(data);
  } catch (e) {
    $("analyzeOut").innerHTML = `<p class="analyze-err">${esc(e.message || e)}</p>`;
  } finally {
    $("btnAnalyze").disabled = false;
  }
}

async function runAnalyzeScreenshot() {
  const input = $("aShot");
  const file = input && input.files && input.files[0];
  if (!file) {
    alert("Выберите скриншот объявления с биржи грузов");
    return;
  }
  const base = ($("aBase").value || $("pBase").value || "москва").trim();
  const live = $("aLive") ? $("aLive").checked : true;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("base", base);
  fd.append("live", live ? "true" : "false");

  const btn = $("btnAnalyzeShot");
  if (btn) btn.disabled = true;
  $("analyzeOut").hidden = false;
  $("analyzeOut").innerHTML = `<p class="analyze-loading">Читаем скрин…</p>`;
  try {
    const headers = {};
    const tok = writeToken();
    if (tok) headers["X-Hub-Token"] = tok;
    const r = await fetch("/api/analyze/screenshot", { method: "POST", body: fd, headers });
    const rawText = await r.text();
    let data = null;
    try {
      data = rawText ? JSON.parse(rawText) : null;
    } catch (_) {
      data = null;
    }
    if (!r.ok) {
      const msg = (data && data.error)
        || (rawText && !rawText.includes("<") ? rawText.slice(0, 200) : null)
        || "Сервер не ответил на разбор скрина. Попробуйте ещё раз или заполните поля вручную.";
      throw new Error(msg);
    }
    if (!data) throw new Error("Пустой ответ сервера");
    if (!data.ok) {
      $("analyzeOut").innerHTML = `<p class="analyze-err">${esc(data.error || "Ошибка")}</p>`;
      return;
    }
    const analysis = data.analysis || {};
    if (!analysis.ok) {
      $("analyzeOut").innerHTML = `<p class="analyze-err">${esc(analysis.error || "Не удалось посчитать")}</p>`;
      return;
    }
    const t = data.targets || {};
    const ex = data.extracted || {};
    if (t.destination && $("aDest")) $("aDest").value = t.destination;
    if (t.from_city && $("aFrom")) $("aFrom").value = t.from_city;
    else if (ex.from_city && $("aFrom")) $("aFrom").value = ex.from_city;
    if (t.offer_rub != null && $("aOffer")) $("aOffer").value = Math.round(t.offer_rub);
    if (t.listed_route_km != null && $("aKm")) $("aKm").value = Math.round(t.listed_route_km);
    else if (ex.route_km != null && $("aKm")) $("aKm").value = Math.round(ex.route_km);
    if (t.base && $("aBase")) $("aBase").value = t.base;
    renderAnalyzeResult(analysis, {
      advice: data.advice,
      extracted: data.extracted,
      method: data.method,
    });
  } catch (e) {
    $("analyzeOut").innerHTML = `<p class="analyze-err">${esc(e.message || e)}</p>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

const btnAnalyze = $("btnAnalyze");
if (btnAnalyze) {
  btnAnalyze.addEventListener("click", () => runAnalyze().catch(alert));
}
const btnAnalyzeShot = $("btnAnalyzeShot");
if (btnAnalyzeShot) {
  btnAnalyzeShot.addEventListener("click", () => runAnalyzeScreenshot().catch(alert));
}
const shotInput = $("aShot");
const shotDrop = document.querySelector(".shot-drop");
if (shotInput) {
  shotInput.addEventListener("change", () => {
    const f = shotInput.files && shotInput.files[0];
    const name = $("aShotName");
    if (name) {
      name.hidden = !f;
      name.textContent = f ? f.name : "";
    }
    const prev = $("aShotPreview");
    const img = $("aShotImg");
    if (prev && img) {
      if (f && f.type.startsWith("image/")) {
        const url = URL.createObjectURL(f);
        img.onload = () => { try { URL.revokeObjectURL(url); } catch (_) {} };
        img.src = url;
        prev.hidden = false;
      } else {
        prev.hidden = true;
        img.removeAttribute("src");
      }
    }
  });
}
if (shotDrop && shotInput) {
  ["dragenter", "dragover"].forEach((ev) => {
    shotDrop.addEventListener(ev, (e) => {
      e.preventDefault();
      shotDrop.classList.add("drag");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    shotDrop.addEventListener(ev, (e) => {
      e.preventDefault();
      shotDrop.classList.remove("drag");
    });
  });
  shotDrop.addEventListener("drop", (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files[0]) {
      try {
        const dt = new DataTransfer();
        dt.items.add(files[0]);
        shotInput.files = dt.files;
      } catch {
        /* some browsers block programmatic FileList */
      }
      shotInput.dispatchEvent(new Event("change"));
      if (shotInput.files && shotInput.files[0]) {
        /* ok */
      } else {
        alert("Выберите файл через кнопку — drag&drop в этом браузере недоступен");
      }
    }
  });
}
["aDest", "aOffer", "aBase", "aFrom", "aKm"].forEach((id) => {
  const el = $(id);
  if (!el) return;
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runAnalyze().catch(alert);
  });
});

const clearMutes = $("btnClearMutes");
if (clearMutes) {
  clearMutes.addEventListener("click", async () => {
    await api("/api/mute", { method: "DELETE" });
    await loadList();
  });
}

document.querySelectorAll("[data-preset]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const p = PRESETS[btn.dataset.preset];
    if (!p) return;
    document.querySelectorAll("[data-preset]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $("pBase").value = p.base || "";
    $("pBody").value = p.body || "";
    $("pTonnage").value = p.tonnage ?? "";
    $("pRadius").value = p.radius ?? "";
    $("pRadiusFar").value = p.radius_far ?? "";
    $("pBackhaul").checked = !!p.backhaul;
    if (p.body === "reefer") $("reefer").checked = true;
    await saveProfile(p);
    await loadList();
  });
});

$("btnScrape").addEventListener("click", async () => {
  $("btnScrape").disabled = true;
  try {
    await api("/api/scrape?quick=true", { method: "POST" });
    $("meta").textContent = "Обновление запущено…";
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const st = await api("/api/scrape/status");
      if (!st.running) break;
    }
    await refreshHealth();
    await loadList();
  } catch (e) {
    alert(e.message || e);
  } finally {
    $("btnScrape").disabled = false;
  }
});

["q", "from", "to"].forEach((id) => {
  $(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadList().catch(alert);
  });
});

function renderMarketScale(market) {
  if (!market) return "";
  if (!market.ok) {
    return `<div class="market-scale weak">
      <div class="ati-label">Рынок по плечу</div>
      <div class="muted">${esc(market.reason || "мало данных")} · n=${market.n ?? 0}</div>
      ${market.your_min_rub != null ? `<div class="muted">ваша мин. <b>${fmtRub(market.your_min_rub)}</b></div>` : ""}
    </div>`;
  }
  const sc = market.scale || {};
  const vsLabel = market.vs === "in_band" ? "в рынке" : (market.vs === "above_market" ? "выше рынка" : "ниже рынка");
  return `<div class="market-scale ${esc(market.vs || "")}">
    <div class="ati-label">Рынок по плечу · n=${market.n} · ${market.window_days || 7} дн${market.scope ? ` · ${esc(market.scope)}` : ""}${market.unit === "ppk" ? " · ₽/км" : ""}</div>
    <div class="ms-track" aria-hidden="true">
      <i class="ms-band" style="left:${sc.p25_pct || 0}%; width:${Math.max(2, (sc.p75_pct || 100) - (sc.p25_pct || 0))}%"></i>
      <i class="ms-mark med" style="left:${sc.median_pct || 50}%" title="медиана"></i>
      <i class="ms-mark you" style="left:${sc.your_pct || 50}%" title="ваша мин."></i>
    </div>
    <div class="ms-legend">
      <span>p25 ${fmtRub(market.p25_rub)}</span>
      <span>мед. ${fmtRub(market.median_total_rub)}</span>
      <span>p75 ${fmtRub(market.p75_rub)}</span>
    </div>
    <div class="market-line">ваша мин. <b>${fmtRub(market.your_min_rub)}</b> · Δ ${fmtRub(market.delta_rub)} · ${esc(vsLabel)}</div>
  </div>`;
}

let seenHotIds = new Set();
let hotNotifyReady = false;

function maybeNotifyHot(items) {
  const hot = (items || []).filter((it) => groupOf(it) === "hot");
  if (!hot.length) return;
  const fresh = hot.filter((it) => !seenHotIds.has(String(it.id || it.external_id)));
  hot.forEach((it) => seenHotIds.add(String(it.id || it.external_id)));
  if (seenHotIds.size > 400) {
    seenHotIds = new Set([...seenHotIds].slice(-200));
  }
  if (!fresh.length || !hotNotifyReady) return;
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  const it = fresh[0];
  try {
    new Notification("Горячая заявка", {
      body: routeText(it),
      tag: `hot-${it.id || it.external_id}`,
    });
  } catch (_) {}
}

function openFiltersSheet() {
  const sheet = $("filtersSheet");
  if (!sheet) return;
  sheet.classList.add("open");
  sheet.setAttribute("aria-hidden", "false");
  document.body.classList.add("sheet-open");
}

function closeFiltersSheet() {
  const sheet = $("filtersSheet");
  if (!sheet) return;
  sheet.classList.remove("open");
  sheet.setAttribute("aria-hidden", "true");
  document.body.classList.remove("sheet-open");
}

function wireFiltersSheet() {
  const openBtn = $("btnOpenFilters");
  const closeBtn = $("btnCloseFilters");
  const backdrop = $("filtersBackdrop");
  if (openBtn) openBtn.addEventListener("click", openFiltersSheet);
  if (closeBtn) closeBtn.addEventListener("click", () => {
    closeFiltersSheet();
    loadList().catch(alert);
  });
  if (backdrop) backdrop.addEventListener("click", closeFiltersSheet);
  const apply = $("btnApply");
  if (apply) {
    apply.addEventListener("click", () => closeFiltersSheet());
  }
}

function registerPwa() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  if (typeof Notification !== "undefined" && Notification.permission === "default") {
    // Ask once after first interaction
    const ask = () => {
      Notification.requestPermission().then((p) => { hotNotifyReady = p === "granted"; });
      window.removeEventListener("click", ask);
    };
    window.addEventListener("click", ask, { once: true });
  } else {
    hotNotifyReady = typeof Notification !== "undefined" && Notification.permission === "granted";
  }
}

(async function boot() {
  writeToken();
  wireFiltersSheet();
  registerPwa();
  const closeBtn = $("parseSummaryClose");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      parseSummaryDismissed = true;
      const box = $("parseSummary");
      if (box) box.hidden = true;
    });
  }
  await loadProfile();
  await refreshHealth();
  await loadList();
  setInterval(() => refreshHealth().catch(() => {}), 20000);
  setInterval(() => loadList().catch(() => {}), 45000);
})();
