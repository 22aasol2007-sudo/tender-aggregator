const $ = (id) => document.getElementById(id);
let lastHealthAt = 0;
let lastTgDown = false;
let lastMuted = [];
let activeChannel = "all";

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
  const t = Number(item.created_at || item.scraped_at || 0);
  if (!t) return "";
  const d = new Date(t * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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
  if (a && b) return `${a} → ${b}`;
  if (a || b) return `${a || "?"} → ${b || "?"}`;
  const title = (item.title || "").trim();
  if (title && !/^\?\s*→\s*\?$/.test(title)) return title;
  return "Маршрут не указан";
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
    const reasons = (meta && meta.filter_reasons) || [];
    const tip = reasons.length
      ? reasons.join(" · ")
      : "Снимите узкие фильтры или обновите источники.";
    const tgCta = lastTgDown
      ? `<a class="btn" href="/tg-login">Войти в Telegram</a>`
      : "";
    list.innerHTML = `<div class="empty">
      <div>Ничего не найдено</div>
      <div style="margin-top:8px">${esc(tip)}</div>
      <div class="empty-actions">
        ${tgCta}
        <button type="button" class="btn ghost" id="emptyReset">Сбросить фильтры</button>
      </div>
    </div>`;
    const btn = $("emptyReset");
    if (btn) btn.onclick = () => { resetFilters(); loadList().catch(alert); };
    return;
  }

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
  if (item.route_km != null) facts.push(`<span>${esc(Math.round(Number(item.route_km)))} км</span>`);
  if (item.load_date) facts.push(`<span>${esc(item.load_date)}</span>`);

  const meta = [];
  meta.push(`<span class="source-tag">${esc(sourceLabel(item.source))}</span>`);
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
  params.set("min_score", minScore);
  params.set("sort", $("sort").value || "date");
  params.set("shipper_only", $("shipperOnly").checked ? "true" : "false");
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
  $("minScore").value = "40";
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
  $("btnMore").textContent = el.hidden ? "Ещё фильтры" : "Скрыть фильтры";
});
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    setChannel(btn.dataset.channel || "all");
    loadList().catch(alert);
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

(async function boot() {
  writeToken();
  await loadProfile();
  await refreshHealth();
  await loadList();
  setInterval(() => refreshHealth().catch(() => {}), 20000);
  setInterval(() => loadList().catch(() => {}), 45000);
})();
