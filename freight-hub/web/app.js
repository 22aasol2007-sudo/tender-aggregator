const $ = (id) => document.getElementById(id);
let lastHealthAt = 0;

async function api(path, opts) {
  const r = await fetch(path, opts);
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

function contactHref(item) {
  const phones = parseList(item.phones);
  const contacts = parseList(item.contacts);
  if (phones[0]) return { href: `tel:${phones[0]}`, label: phones[0] };
  if (contacts[0]) return { href: `https://t.me/${contacts[0]}`, label: `@${contacts[0]}` };
  if (item.url) return { href: item.url, label: "Открыть" };
  return null;
}

function muteKey(item) {
  if (item.from_city && item.to_city) return `${item.from_city}-${item.to_city}`;
  return item.from_city || item.to_city || "";
}

function ageSec(item) {
  const t = Number(item.scraped_at || item.created_at || 0);
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

function render(items, meta) {
  const list = $("list");
  if (!items.length) {
    const reasons = (meta && meta.filter_reasons) || [];
    const tip = reasons.length
      ? reasons.join(" · ")
      : "Снимите узкие фильтры или обновите источники.";
    list.innerHTML = `<div class="empty">
      <div>Ничего не найдено</div>
      <div style="margin-top:8px">${esc(tip)}</div>
      <button type="button" class="btn" id="emptyReset">Сбросить фильтры</button>
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
}

function cardHtml(item) {
  const fresh = ageSec(item) <= 300;
  const contact = contactHref(item);
  const facts = [];
  if (item.tonnage != null) facts.push(`<span><b>${esc(item.tonnage)}</b> т</span>`);
  if (item.volume_m3 != null) facts.push(`<span><b>${esc(item.volume_m3)}</b> м³</span>`);
  if (item.body_type) facts.push(`<span>${esc(item.body_type)}</span>`);
  if (item.price) facts.push(`<span><b>${esc(item.price)}</b></span>`);
  if (item.load_date) facts.push(`<span>${esc(item.load_date)}</span>`);

  const meta = [];
  meta.push(`<span class="source-tag ${esc(item.source || "")}">${esc(item.source || "")}</span>`);
  if (item.km_from != null) meta.push(`погр. ${Math.round(item.km_from)} км`);
  if (item.km_to != null) meta.push(`выгр. ${Math.round(item.km_to)} км`);

  const why = Array.isArray(item.why) && item.why.length
    ? `<div class="why">${esc(item.why.join(" · "))}</div>`
    : "";
  const mk = muteKey(item);
  const score = Math.max(0, Math.min(100, Number(item.score || 0)));
  const cta = contact
    ? `<a class="cta" href="${esc(contact.href)}" target="_blank" rel="noopener">Связаться</a>`
    : `<button type="button" class="cta show" data-full="${encodeURIComponent(item.body || "")}">Открыть</button>`;

  return `<article class="card${fresh ? " fresh" : ""}">
    <div>
      <div class="route">${esc(routeText(item))}</div>
      <div class="facts">${facts.join("") || "<span>детали в тексте</span>"}</div>
      <div class="meta-row">${meta.join('<span>·</span>')}</div>
      ${why}
    </div>
    <div class="actions">
      <div class="score-bar" title="Скор ${score}"><span style="width:${score}%"></span></div>
      ${cta}
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

    const banner = $("banner");
    if (h.hints && h.hints.length) {
      banner.hidden = false;
      const text = h.hints.join(" ");
      if (text.includes("/tg-login")) {
        banner.innerHTML = `${esc(text)} — <a href="/tg-login">войти в Telegram</a>`;
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
  }
}

function currentParams() {
  const params = new URLSearchParams();
  const q = $("q").value.trim();
  const source = $("source").value;
  const body = $("body").value;
  const frm = $("from").value.trim();
  const to = $("to").value.trim();
  const minScore = $("minScore").value || "40";
  if (q) params.set("q", q);
  if (source) params.set("source", source);
  if (body) params.set("body_type", body);
  if (frm) params.set("from", frm);
  if (to) params.set("to", to);
  params.set("min_score", minScore);
  params.set("sort", $("sort").value || "time");
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

function resetFilters() {
  $("q").value = "";
  $("source").value = "";
  $("from").value = "";
  $("to").value = "";
  $("body").value = "";
  $("sort").value = "time";
  $("shipperOnly").checked = true;
  $("reefer").checked = false;
  $("hotOnly").checked = false;
  $("minScore").value = "40";
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
  await api("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  $("meta").textContent = "Профиль сохранён";
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
  $("btnScrape").textContent = "…";
  try {
    const start = await api("/api/scrape?quick=true", { method: "POST" });
    $("btnScrape").disabled = false;
    $("btnScrape").textContent = "Обновить";
    if (start.busy) {
      $("meta").textContent = "Сбор уже идёт…";
      return;
    }
    $("meta").textContent = "Быстрый сбор…";
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000));
      const last = await api("/api/scrape/status");
      await loadList().catch(() => {});
      if (!last.running) {
        await refreshHealth();
        await loadList();
        $("meta").textContent = "Источники обновлены";
        return;
      }
    }
    $("meta").textContent = "Сбор ещё идёт…";
  } catch (e) {
    $("btnScrape").disabled = false;
    $("btnScrape").textContent = "Обновить";
    alert(String(e));
  }
});

["q", "from", "to", "minScore"].forEach((id) => {
  $(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadList().catch(alert);
  });
});
["shipperOnly", "reefer", "hotOnly", "source", "sort"].forEach((id) => {
  const el = $(id);
  if (el) el.addEventListener("change", () => loadList().catch(alert));
});

setInterval(() => {
  if (lastHealthAt) $("updatedAgo").textContent = fmtAgo((Date.now() - lastHealthAt) / 1000);
}, 5000);

refreshHealth();
loadProfile();
loadList().catch(console.error);
setInterval(() => {
  refreshHealth();
  loadList().catch(() => {});
}, 45000);
