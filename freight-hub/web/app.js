const $ = (id) => document.getElementById(id);

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
  if (title && !/^\?\s*→\s*\?$/.test(title) && !title.includes(" → ?") && !title.startsWith("? →")) {
    return title;
  }
  const line = String(item.body || "")
    .split(/\n/)
    .map((s) => s.trim())
    .find((s) => s.length > 4 && !/^https?:/i.test(s));
  return line ? line.slice(0, 90) : "Маршрут не указан";
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

function bits(item) {
  const out = [];
  if (item.tonnage != null) out.push(`${item.tonnage} т`);
  if (item.volume_m3 != null) out.push(`${item.volume_m3} м³`);
  if (item.body_type) out.push(item.body_type);
  if (item.load_date) out.push(item.load_date);
  if (item.price) out.push(item.price);
  if (item.km_from != null) out.push(`погр. ${Math.round(item.km_from)} км от Мск`);
  if (item.km_to != null) out.push(`выгр. ${Math.round(item.km_to)} км от Мск`);
  const temps = parseList(item.temps);
  if (temps.length) out.push(temps.slice(0, 3).join(" "));
  out.push(item.kind || "—");
  return out;
}

function contactBits(item) {
  const phones = parseList(item.phones);
  const contacts = parseList(item.contacts);
  return [
    ...phones.map((p) => `<a class="bit contact" href="tel:${esc(p)}">${esc(p)}</a>`),
    ...contacts.map((c) => `<a class="bit contact" href="https://t.me/${esc(c)}" target="_blank" rel="noopener">@${esc(c)}</a>`),
  ].join("");
}

function muteKey(item) {
  if (item.from_city && item.to_city) return `${item.from_city}-${item.to_city}`;
  return item.from_city || item.to_city || "";
}

function render(items) {
  const list = $("list");
  if (!items.length) {
    const src = $("source")?.value;
    const tip = src
      ? `Сейчас выбран источник «${src}». Поставь «Все источники» или сними лишние фильтры.`
      : "Проверь фильтры / скор, нажми «Обновить источники».";
    list.innerHTML = `<div class="empty">Ничего не найдено. ${tip}</div>`;
    return;
  }
  list.innerHTML = items
    .map((item) => {
      const b = bits(item)
        .map((x) => `<span class="bit">${esc(x)}</span>`)
        .join("");
      const contacts = contactBits(item);
      const src = esc(item.source || "");
      const url = item.url
        ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">Оригинал</a>`
        : "";
      const mk = muteKey(item);
      const muteBtn = mk
        ? `<button type="button" class="mute" data-dir="${esc(mk)}">Не интересно</button>`
        : "";
      return `<article class="card">
        <div>
          <div class="source ${src}">${src}</div>
          <div class="route">${esc(routeText(item))}</div>
          <div class="bits">${b}${contacts}</div>
        </div>
        <div class="actions">
          <div class="score-badge">${esc(item.score)}/100</div>
          <button type="button" class="show" data-full="${encodeURIComponent(item.body || "")}">Показать</button>
          ${muteBtn}
          ${url}
        </div>
      </article>`;
    })
    .join("");

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

async function refreshHealth() {
  try {
    const h = await api("/api/health");
    const parts = Object.entries(h.by_source || {})
      .map(([k, v]) => `${k}:${v}`)
      .join(" · ");
    const th = h.tg_health || {};
    const mh = h.max_health || {};
    const tgExtra = h.tg
      ? `res:${th.resolved || 0}/${th.watched || "?"}`
      : "off";
    const maxExtra = h.max
      ? `res:${mh.resolved || 0}/${mh.watched || "?"}`
      : (mh.note || "off");
    $("health").textContent = `loads ${h.total_loads} · ${parts || "—"} · tg:${tgExtra} · max:${maxExtra}`;
    const banner = $("banner");
    if (h.hints && h.hints.length) {
      banner.hidden = false;
      const text = h.hints.join(" ");
      if (text.includes("/tg-login")) {
        banner.innerHTML = `${esc(text)} — <a href="/tg-login" style="color:inherit;font-weight:700">открыть вход</a>`;
      } else {
        banner.textContent = text;
      }
    } else {
      banner.hidden = true;
      banner.textContent = "";
    }
  } catch (e) {
    $("health").textContent = "offline";
  }
}

async function loadList() {
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
  if ($("hotOnly") && $("hotOnly").checked) params.set("hot", "true");
  params.set("limit", "300");
  const data = await api(`/api/loads?${params}`);
  $("meta").textContent = `Показано: ${data.count}`;
  render(data.items || []);
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

$("btnApply").addEventListener("click", () => loadList().catch(alert));
$("btnSaveProfile").addEventListener("click", async () => {
  const body = {
    base: $("pBase").value.trim() || null,
    body: $("pBody").value || null,
    tonnage: $("pTonnage").value ? Number($("pTonnage").value) : null,
    radius: $("pRadius").value ? Number($("pRadius").value) : null,
    radius_far: $("pRadiusFar").value ? Number($("pRadiusFar").value) : null,
    backhaul: $("pBackhaul").checked,
  };
  await api("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  $("meta").textContent = "Профиль сохранён";
});

$("btnScrape").addEventListener("click", async () => {
  $("btnScrape").disabled = true;
  $("btnScrape").textContent = "Запуск…";
  try {
    const start = await api("/api/scrape?quick=true", { method: "POST" });
    $("btnScrape").disabled = false;
    $("btnScrape").textContent = "Обновить источники";
    if (start.busy) {
      $("meta").textContent = "Сбор уже идёт в фоне…";
      return;
    }
    $("meta").textContent = "Быстрый сбор в фоне…";
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000));
      const last = await api("/api/scrape/status");
      await loadList().catch(() => {});
      if (!last.running) {
        const summary = (last.results || [])
          .map((r) => (r.ok ? `${r.source}+${r.added}/${r.total || 0}` : `${r.source}:err`))
          .join(" · ");
        const sec =
          last.finished_at && last.started_at
            ? Math.max(1, Math.round(last.finished_at - last.started_at))
            : "?";
        $("meta").textContent = `Сбор (${sec}с): ${summary || "—"}`;
        await refreshHealth();
        await loadList();
        return;
      }
    }
    $("meta").textContent = "Сбор ещё идёт в фоне…";
  } catch (e) {
    $("btnScrape").disabled = false;
    $("btnScrape").textContent = "Обновить источники";
    alert(String(e));
  }
});

["q", "from", "to", "minScore"].forEach((id) => {
  $(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadList().catch(alert);
  });
});

["shipperOnly", "reefer", "hotOnly"].forEach((id) => {
  const el = $(id);
  if (el) el.addEventListener("change", () => loadList().catch(alert));
});

refreshHealth();
loadProfile();
loadList().catch(console.error);
setInterval(() => {
  refreshHealth();
  loadList().catch(() => {});
}, 45000);
