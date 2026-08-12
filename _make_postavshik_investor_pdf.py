# -*- coding: utf-8 -*-
"""Postavshik investor deck v5 — Calibri/Candara, fixed layout, 3-month growth deep dive."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(r"C:\Users\windo\Projects\tender-aggregator")
OUT = ROOT / "Postavshik_investor_deck.pdf"
CHARTS = ROOT / "_deck_charts"
CHARTS.mkdir(exist_ok=True)

# Soft readable UI fonts (Segoe for body, Candara for titles)
pdfmetrics.registerFont(TTFont("Body", r"C:\Windows\Fonts\segoeui.ttf"))
pdfmetrics.registerFont(TTFont("Body-Bold", r"C:\Windows\Fonts\segoeuib.ttf"))
pdfmetrics.registerFont(TTFont("Display", r"C:\Windows\Fonts\Candara.ttf"))
pdfmetrics.registerFont(TTFont("Display-Bold", r"C:\Windows\Fonts\Candarab.ttf"))

INK = HexColor("#1A1F26")
MUTED = HexColor("#4B5563")
LINE = HexColor("#D1D9E0")
BG = HexColor("#F5F7F9")
ACCENT = HexColor("#0F766E")
ACCENT2 = HexColor("#0D9488")
ACCENT_DK = HexColor("#115E59")
CARD = HexColor("#FFFFFF")
WARN = HexColor("#C2410C")
DANGER = HexColor("#BE123C")
OK = HexColor("#15803D")
SOFT = HexColor("#CCFBF1")

M = dict(
    ink="#1A1F26",
    muted="#4B5563",
    accent="#0F766E",
    accent2="#0D9488",
    warn="#C2410C",
    danger="#BE123C",
    ok="#15803D",
    soft="#CCFBF1",
    gray="#94A3B8",
)

PAGE_W, PAGE_H = A4
MARGIN = 12 * mm
CW = PAGE_W - 2 * MARGIN
TOP = PAGE_H - 26 * mm
BOT = 16 * mm
TOTAL = 14


def style():
    plt.rcParams.update(
        {
            "font.family": "Segoe UI",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "axes.facecolor": "#FFFFFF",
            "figure.facecolor": "#FFFFFF",
            "axes.edgecolor": "#D1D9E0",
            "axes.labelcolor": M["muted"],
            "xtick.color": M["muted"],
            "ytick.color": M["muted"],
            "text.color": M["ink"],
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def save(fig, name: str, bottom: float = 0.12, left: float = 0.12) -> Path:
    path = CHARTS / name
    fig.subplots_adjust(left=left, right=0.98, top=0.88, bottom=bottom)
    fig.savefig(path, facecolor="white", dpi=180)
    plt.close(fig)
    return path


def chart_two_products() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 2.35))
    ax.barh([1], [1], color=M["accent"], height=0.62)
    ax.barh([0], [1], color=M["ok"], height=0.62)
    ax.text(0.5, 1, "Базовый поиск  ·  список поставщиков  ·  без чужих цен", ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    ax.text(0.5, 0, "Под ключ  ·  сами пишем и торгуемся  ·  отдельная оплата", ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    ax.set_xlim(0, 1)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_title("Две услуги — разная глубина и разная цена", loc="left", fontweight="bold", color=M["ink"])
    for s in ax.spines.values():
        s.set_visible(False)
    return save(fig, "two_products.png")


def chart_market() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 2.85))
    labels = [
        "Гофра РФ  ·  ~360 млрд ₽",
        "Косметика РФ  ·  1,2–1,43 трлн ₽",
        "SRM-софт*  ·  3–5 млрд ₽",
        "Наш старт: гофра×косметика МСК",
    ]
    # Visual weight for story only (not ₽-proportional)
    vals = [9.5, 10, 4.5, 1.8]
    cols = [M["accent"], M["accent2"], M["warn"], M["ok"]]
    y = np.arange(len(labels))
    ax.barh(y, vals, color=cols, height=0.58, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.set_xlim(0, 11)
    ax.set_xticks([])
    ax.set_xlabel("Иллюстрация масштаба (не пропорция в ₽)")
    ax.set_title("Большой рынок товаров ≠ наша выручка", loc="left", fontweight="bold")
    ax.invert_yaxis()
    for sp in ("bottom", "top", "right"):
        ax.spines[sp].set_visible(False)
    return save(fig, "market.png", bottom=0.16, left=0.42)


def chart_demand() -> Path:
    """Why buyers need us now — horizontal bars (no label clash)."""
    style()
    fig, ax = plt.subplots(figsize=(8.2, 3.05))
    drivers = [
        "Нехватка времени снабженца",
        "Давление на цену и срок",
        "Страх ложной цены",
        "Рост ИИ в закупках",
        "Нужна память базы",
    ]
    score = [9.2, 9.0, 8.8, 8.5, 8.0]
    colors = [M["accent"], M["accent"], M["warn"], M["accent2"], M["ok"]]
    y = np.arange(len(drivers))
    ax.barh(y, score, color=colors, height=0.62, zorder=3)
    for yi, s in zip(y, score):
        ax.text(s + 0.12, yi, f"{s}", va="center", fontsize=11, fontweight="bold", color=M["ink"])
    ax.set_yticks(y)
    ax.set_yticklabels(drivers, fontsize=10.5)
    ax.set_xlim(0, 10.8)
    ax.set_xlabel("Сила потребности (0–10) · оценка по трендам, не опрос")
    ax.set_title("Почему отделы закупок готовы пробовать такие сервисы", loc="left", fontweight="bold")
    ax.invert_yaxis()
    return save(fig, "demand.png", bottom=0.16, left=0.32)


def chart_funnel_3m() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 3.15))
    stages = [
        "Контакты в нише",
        "Разговоры / пилоты",
        "Партнёры с базой",
        "Платящие подписки",
        "Сделки под ключ",
    ]
    vals = [80, 18, 8, 6, 4]
    y = np.arange(len(stages))
    colors = [M["gray"], M["accent2"], M["accent"], M["ok"], M["warn"]]
    ax.barh(y, vals, color=colors, height=0.65, zorder=3)
    for yi, v in zip(y, vals):
        ax.text(v + 1.5, yi, str(v), va="center", fontsize=12, fontweight="bold", color=M["ink"])
    ax.set_yticks(y)
    ax.set_yticklabels(
        [
            "Контакты",
            "Разговоры",
            "Партнёры",
            "Подписки",
            "Под ключ",
        ],
        fontsize=11,
    )
    ax.invert_yaxis()
    ax.set_xlabel("")
    ax.set_xlim(0, 100)
    ax.set_title("Воронка за 90 дней (базовый сценарий)", loc="left", fontweight="bold")
    # value labels already drawn
    fig.text(
        0.28,
        0.04,
        "80 → 18 → 8 → 6 подписок и 4 «под ключ»   ·   только ниша гофры / косметика Москвы",
        fontsize=9,
        color=M["muted"],
    )
    return save(fig, "funnel3m.png", bottom=0.14, left=0.22)


def chart_revenue_3m() -> Path:
    """Monthly bars + cumulative lines — how earnings build over 90 days."""
    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.6, 3.15), gridspec_kw={"width_ratios": [1.15, 1]})
    months = ["Мес. 1", "Мес. 2", "Мес. 3"]
    weak = [0, 40, 90]
    base = [25, 140, 300]
    strong = [60, 220, 480]
    x = np.arange(len(months))
    w = 0.25
    ax1.bar(x - w, weak, width=w, color="#FECACA", label="Слабый")
    ax1.bar(x, base, width=w, color=M["accent"], label="Базовый")
    ax1.bar(x + w, strong, width=w, color=M["ok"], label="Сильный")
    for i in range(3):
        ax1.text(i - w, weak[i] + 10, f"{weak[i]}", ha="center", fontsize=8.5)
        ax1.text(i, base[i] + 10, f"{base[i]}", ha="center", fontsize=9, fontweight="bold")
        ax1.text(i + w, strong[i] + 10, f"{strong[i]}", ha="center", fontsize=8.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(months)
    ax1.set_ylabel("Выручка за месяц, тыс. ₽")
    ax1.set_title("По месяцам", loc="left", fontweight="bold", fontsize=12)
    ax1.legend(frameon=False, fontsize=9, loc="upper left")
    ax1.set_ylim(0, 560)

    cum_w = np.cumsum(weak)
    cum_b = np.cumsum(base)
    cum_s = np.cumsum(strong)
    ax2.plot(months, cum_w, "o-", color="#F87171", lw=2.2, ms=7, label="Слабый → 130")
    ax2.plot(months, cum_b, "o-", color=M["accent"], lw=2.6, ms=8, label="Базовый → 465")
    ax2.plot(months, cum_s, "o-", color=M["ok"], lw=2.2, ms=7, label="Сильный → 760")
    ax2.fill_between(months, cum_b, color=M["soft"], alpha=0.55)
    for xv, yv in zip(months, cum_b):
        ax2.text(xv, yv + 28, f"{yv}", ha="center", fontsize=9, fontweight="bold", color=M["accent"])
    ax2.set_ylabel("Накопительно, тыс. ₽")
    ax2.set_title("Итого за 90 дней", loc="left", fontweight="bold", fontsize=12)
    ax2.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax2.set_ylim(0, 900)
    fig.suptitle("Сколько можем заработать (цель, тыс. ₽)", x=0.06, ha="left", fontsize=13, fontweight="bold", color=M["ink"])
    fig.subplots_adjust(left=0.09, right=0.98, top=0.82, bottom=0.14, wspace=0.32)
    path = CHARTS / "rev3m.png"
    fig.savefig(path, facecolor="white", dpi=180)
    plt.close(fig)
    return path


def chart_mix_3m() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 3.25))
    labels = ["Подписки на поиск", "Услуги под ключ", "Пакеты / разовое"]
    sizes = [210, 220, 35]
    colors = [M["accent"], M["ok"], M["warn"]]
    wedges, _ = ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        wedgeprops={"width": 0.52, "edgecolor": "white", "linewidth": 2},
    )
    ax.text(0, 0.06, "465", ha="center", va="center", fontsize=18, fontweight="bold", color=M["ink"])
    ax.text(0, -0.18, "тыс. ₽", ha="center", va="center", fontsize=11, color=M["muted"])
    ax.set_title("Базовый сценарий — из чего складываются деньги", fontweight="bold", loc="left")
    fig.legend(
        wedges,
        [f"{n}: {v} тыс. ({v / sum(sizes) * 100:.0f}%)" for n, v in zip(labels, sizes)],
        loc="lower center",
        ncol=3,
        frameon=False,
        fontsize=10,
        bbox_to_anchor=(0.5, -0.02),
    )
    return save(fig, "mix3m.png", bottom=0.2, left=0.08)


def chart_path_how() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 2.55))
    steps = ["нед. 1–3", "нед. 4–6", "нед. 7–9", "нед. 10–12"]
    focus = [20, 45, 70, 100]
    ax.fill_between(range(4), focus, color=M["soft"], alpha=0.9)
    ax.plot(range(4), focus, "o-", color=M["accent"], lw=2.8, ms=9)
    labels = ["Знакомства и базы", "Пилоты и списки", "Первые оплаты", "Повторы и кейсы"]
    for i, lab in enumerate(labels):
        ax.text(i, focus[i] + 8, lab, ha="center", fontsize=9.5, color=M["muted"])
    ax.set_xticks(range(4))
    ax.set_xticklabels(steps, fontsize=11)
    ax.set_ylim(0, 125)
    ax.set_ylabel("Готовность ниши, %")
    ax.set_title("Как именно растём: 12 недель", loc="left", fontweight="bold")
    return save(fig, "path12w.png", bottom=0.18)


def chart_pnl_year() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 2.85))
    scenarios = ["Слабый\nгод", "Базовый\nгод", "Удачный\nгод"]
    revenue = [0.6, 2.4, 6.0]
    costs = [1.4, 2.0, 3.8]
    profit = [r - c for r, c in zip(revenue, costs)]
    x = np.arange(len(scenarios))
    ax.bar(x - 0.2, revenue, width=0.4, color=M["accent"], label="Выручка")
    ax.bar(x + 0.2, costs, width=0.4, color=M["gray"], label="Расходы")
    ax.plot(x, profit, "o-", color=M["ok"], lw=2.5, ms=8, label="Прибыль")
    for i, p in enumerate(profit):
        ax.text(i, p + 0.18, f"{p:+.1f}", ha="center", fontsize=11, fontweight="bold", color=M["ok"] if p >= 0 else M["danger"])
    ax.axhline(0, color="#CBD5E1", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(scenarios)
    ax.set_ylabel("млн ₽ / год")
    ax.set_title("Если 3 месяца прошли удачно — горизонт года", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncols=3)
    return save(fig, "pnl.png")


def chart_costs() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(4.5, 3.2))
    sizes = [32, 22, 16, 12, 10, 8]
    labels = ["Люди", "Продажи", "ИИ/поиск", "Серверы", "Бух/налоги", "Прочее"]
    colors = [M["accent"], M["accent2"], M["warn"], "#64748B", M["gray"], "#CBD5E1"]
    ax.pie(sizes, labels=labels, colors=colors, autopct="%1.0f%%", startangle=90, textprops={"fontsize": 10})
    ax.set_title("Куда уходят деньги", fontweight="bold")
    return save(fig, "costs_pie.png")


def chart_unit_cost() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 2.65))
    labels = ["Повтор поиска", "Обычный поиск", "Под ключ"]
    low, high = [5, 40, 800], [25, 180, 3500]
    x = np.arange(len(labels))
    ax.bar(x, high, color="#99F6E4", width=0.55, label="До")
    ax.bar(x, low, color=M["accent"], width=0.55, label="От")
    for i, (a, b) in enumerate(zip(low, high)):
        ax.text(i, b + 90, f"{a}–{b} ₽", ha="center", fontsize=11, color=M["muted"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Себестоимость, ₽")
    ax.set_ylim(0, 4200)
    ax.set_title("Сколько стоит выполнить одну задачу", loc="left", fontweight="bold")
    ax.legend(frameon=False)
    return save(fig, "search_cost.png", bottom=0.16)


def chart_competitors() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 2.9))
    names = ["Postavshik\n(цель)", "ИИ-поиск", "Площадки", "Каталоги", "Excel"]
    honesty = [9, 5, 4, 3, 6]
    depth = [8, 6, 5, 4, 3]
    trust = [8, 5, 6, 4, 7]
    x = np.arange(len(names))
    w = 0.25
    ax.bar(x - w, honesty, width=w, color=M["accent"], label="Честность цен")
    ax.bar(x, depth, width=w, color=M["accent2"], label="Глубина помощи")
    ax.bar(x + w, trust, width=w, color=M["gray"], label="Доверие")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, 11)
    ax.set_ylabel("Оценка 0–10")
    ax.set_title("Где хотим быть сильнее конкурентов", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncols=3, loc="upper right")
    return save(fig, "competitors.png")


def chart_risks() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 3.15))
    risks = [
        "Клиенты не платят",
        "Поставщики молчат",
        "Мало данных в нише",
        "Дорого «под ключ»",
        "Срыв поставки",
        "Скопируют идею",
        "Один основатель",
    ]
    before = [9, 8, 8, 7.5, 9, 6, 7]
    after = [7, 5, 5, 4.5, 6, 4, 6]
    y = np.arange(len(risks))
    ax.barh(y, before, color="#FECDD3", height=0.38, label="Без правил")
    ax.barh(y, after, color=M["accent"], height=0.38, label="С правилами")
    ax.set_yticks(y)
    ax.set_yticklabels(risks, fontsize=10)
    ax.set_xlim(0, 10.5)
    ax.set_xlabel("Насколько опасно (0–10)")
    ax.set_title("Риски: стало спокойнее, но не исчезли", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.invert_yaxis()
    return save(fig, "risks.png", bottom=0.14, left=0.28)


def chart_gtm() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(8.2, 1.95))
    segs = [
        (0, 30, "Месяц 1: двери", M["accent"]),
        (30, 30, "Месяц 2: плотность", M["accent2"]),
        (60, 30, "Месяц 3: деньги", M["ok"]),
    ]
    for s, w, lab, col in segs:
        ax.barh(0, w, left=s, height=0.72, color=col)
        ax.text(s + w / 2, 0, lab, ha="center", va="center", color="white", fontsize=12, fontweight="bold")
    ax.set_xlim(0, 90)
    ax.set_ylim(-0.65, 0.65)
    ax.set_yticks([])
    ax.set_xticks([0, 30, 60, 90])
    ax.set_xlabel("Дни")
    ax.set_title("90 дней — только гофра для косметики Москвы", loc="left", fontweight="bold")
    for sp in ("left", "top", "right"):
        ax.spines[sp].set_visible(False)
    return save(fig, "gtm.png")


# ─── PDF helpers ─────────────────────────────────────────────────
def bg(c):
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)


def header(c, title: str, page: int):
    bg(c)
    c.setFillColor(ACCENT_DK)
    c.rect(0, PAGE_H - 22 * mm, PAGE_W, 22 * mm, fill=1, stroke=0)
    c.setFillColor(ACCENT2)
    c.rect(0, PAGE_H - 22 * mm, 3.2 * mm, 22 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Body", 8.5)
    c.drawString(MARGIN, PAGE_H - 7.5 * mm, "POSTAVSHIK  ·  ИП Чебан")
    c.setFont("Display-Bold", 14)
    t = title
    while c.stringWidth(t, "Display-Bold", 14) > CW - 36 * mm and len(t) > 5:
        t = t[:-2]
    c.drawString(MARGIN, PAGE_H - 16 * mm, t)
    c.setFont("Body-Bold", 10)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm, f"{page} / {TOTAL}")


def footer(c):
    c.setStrokeColor(LINE)
    c.line(MARGIN, 11 * mm, PAGE_W - MARGIN, 11 * mm)
    c.setFillColor(MUTED)
    c.setFont("Body", 8)
    c.drawString(MARGIN, 6 * mm, "Конфиденциально · «цель/оценка» — не обещание")


def wrap(c, text, x, y, max_w, font="Body", size=10.5, leading=13.5, color=INK) -> float:
    c.setFont(font, size)
    c.setFillColor(color)
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines):
        c.drawString(x, y - i * leading, line)
    return len(lines) * leading


def card(c, x, y, w, h, accent=False):
    c.setFillColor(CARD)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.7)
    c.roundRect(x, y - h, w, h, 2.2 * mm, fill=1, stroke=1)
    if accent:
        c.setFillColor(ACCENT)
        c.rect(x, y - h, 2.2 * mm, h, fill=1, stroke=0)


def stat(c, x, y, w, h, value, label, tone=ACCENT):
    card(c, x, y, w, h, True)
    c.setFillColor(tone)
    c.setFont("Display-Bold", 16)
    # fit value
    v = value
    while c.stringWidth(v, "Display-Bold", 16) > w - 8 * mm and len(v) > 3:
        v = v[:-2] + "…"
    c.drawString(x + 4 * mm, y - 11 * mm, v)
    wrap(c, label, x + 4 * mm, y - 18.5 * mm, w - 7 * mm, size=9, leading=11, color=MUTED)


def img_fit(c, path: Path, x, y_top, w, h):
    """Draw image fitted into box without cropping text (contain)."""
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    dx = x + (w - dw) / 2
    dy = y_top - h + (h - dh) / 2
    c.drawImage(img, dx, dy, width=dw, height=dh, mask="auto")


def table(c, x, y, col_ws, headers, rows, row_h=9.5 * mm, fs=9.5):
    tw = sum(col_ws)
    hh = 8.2 * mm
    c.setFillColor(SOFT)
    c.rect(x, y - hh, tw, hh, fill=1, stroke=0)
    xx = x
    c.setFillColor(MUTED)
    c.setFont("Body-Bold", fs)
    for i, h in enumerate(headers):
        c.drawString(xx + 1.6 * mm, y - hh + 2.4 * mm, h)
        xx += col_ws[i]
    yy = y - hh
    for ri, row in enumerate(rows):
        yy -= row_h
        if ri % 2 == 0:
            c.setFillColor(HexColor("#FAFCFC"))
            c.rect(x, yy, tw, row_h, fill=1, stroke=0)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.35)
        c.line(x, yy, x + tw, yy)
        xx = x
        for i, cell in enumerate(row):
            c.setFillColor(INK)
            c.setFont("Body", fs)
            t = str(cell)
            mw = col_ws[i] - 3 * mm
            while c.stringWidth(t, "Body", fs) > mw and len(t) > 3:
                t = t[:-2]
            if t != str(cell):
                t = t[:-1] + "…"
            c.drawString(xx + 1.6 * mm, yy + 2.8 * mm, t)
            xx += col_ws[i]
    return yy


def bullet(c, x, y, text, max_w, size=10.5, leading=13):
    c.setFillColor(ACCENT)
    c.circle(x + 1.3 * mm, y + 1.4 * mm, 1.3 * mm, fill=1, stroke=0)
    return wrap(c, text, x + 5.2 * mm, y, max_w - 5.2 * mm, size=size, leading=leading)


# ─── Pages ───────────────────────────────────────────────────────
def p_cover(c, ch):
    c.setFillColor(ACCENT_DK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.circle(PAGE_W + 5 * mm, PAGE_H - 20 * mm, 58 * mm, fill=1, stroke=0)
    c.setFillColor(ACCENT2)
    c.circle(-25 * mm, 40 * mm, 70 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#0F4C49"))
    c.rect(0, PAGE_H - 92 * mm, PAGE_W, 92 * mm, fill=1, stroke=0)

    c.setFillColor(HexColor("#99F6E4"))
    c.setFont("Body-Bold", 10)
    c.drawString(MARGIN, PAGE_H - 16 * mm, "ОБЗОР ДЛЯ ИНВЕСТОРА  ·  АВГУСТ 2026")
    c.setFillColor(white)
    c.setFont("Display-Bold", 42)
    c.drawString(MARGIN, PAGE_H - 42 * mm, "Postavshik")
    wrap(
        c,
        "Находим поставщиков без ложных цен. Отдельно ведём закупку под ключ — сами пишем, собираем ответы и договариваемся.",
        MARGIN,
        PAGE_H - 55 * mm,
        CW - 10 * mm,
        size=12.5,
        leading=16,
        color=HexColor("#CCFBF1"),
    )

    y = PAGE_H - 105 * mm
    for k, v in [
        ("Кто", "ИП Чебан"),
        ("Сейчас", "Продукт собирается · продаж пока нет"),
        ("Старт", "Косметика Москвы + гофрокоробки"),
        ("Деньги", "Подписка на поиск + услуга под ключ"),
    ]:
        c.setFillColor(HexColor("#5EEAD4"))
        c.setFont("Body-Bold", 9.5)
        c.drawString(MARGIN, y, k.upper())
        c.setFillColor(white)
        c.setFont("Body-Bold", 12.5)
        c.drawString(MARGIN + 30 * mm, y, v)
        y -= 10 * mm

    c.setFillColor(CARD)
    c.roundRect(MARGIN, 14 * mm, CW, 56 * mm, 3 * mm, fill=1, stroke=0)
    img_fit(c, ch["two"], MARGIN + 2 * mm, 66 * mm, CW - 4 * mm, 44 * mm)
    c.setFillColor(MUTED)
    c.setFont("Body", 9)
    c.drawString(MARGIN + 3 * mm, 17 * mm, "Правило: чужие цены и чужие КП не показываем без просьбы клиента")


def p_problem(c, ch):
    header(c, "Какую боль закрываем", 2)
    y = TOP
    h = wrap(c, "Закупкам нужен список кого звать — и уверенность, что цифра на экране не обманет.", MARGIN, y, CW, size=12, leading=15)
    y -= h + 5 * mm
    items = [
        ("Долго и вручную", "Письма, звонки, таблицы. На одну закупку — часы и дни."),
        ("Цены обманывают", "«От 40 ₽» с сайта или из чужого КП редко равно вашей сделке."),
        ("Знания уходят", "Уволился снабженец — база и опыт пропали."),
        ("Страшно ошибиться", "Дешёвый поставщик срывает срок — убыток больше экономии."),
    ]
    w = (CW - 3 * mm) / 2
    for i, (t, d) in enumerate(items):
        x = MARGIN + (i % 2) * (w + 3 * mm)
        yy = y - (i // 2) * 38 * mm
        card(c, x, yy, w, 35 * mm, True)
        c.setFillColor(INK)
        c.setFont("Body-Bold", 12)
        c.drawString(x + 5 * mm, yy - 11 * mm, t)
        wrap(c, d, x + 5 * mm, yy - 20 * mm, w - 9 * mm, size=10.5, leading=13.5, color=MUTED)
    y -= 82 * mm
    card(c, MARGIN, y, CW, 48 * mm, True)
    c.setFillColor(WARN)
    c.setFont("Body-Bold", 12)
    c.drawString(MARGIN + 5 * mm, y - 11 * mm, "Наш ответ")
    wrap(
        c,
        "В обычном поиске не называем цены других производств и не пересылаем их КП. Даём сильный список и ориентир «как бывает в среднем». Живые цены и торг — только в услуге «под ключ», если клиент сам попросил.",
        MARGIN + 5 * mm,
        y - 22 * mm,
        CW - 10 * mm,
        size=11,
        leading=14.5,
    )
    footer(c)


def p_products(c, ch):
    header(c, "Две услуги", 3)
    y = TOP
    img_fit(c, ch["two"], MARGIN, y, CW, 36 * mm)
    y -= 40 * mm
    w = (CW - 3 * mm) / 2
    card_h = y - (BOT + 2 * mm)
    card(c, MARGIN, y, w, card_h, True)
    c.setFillColor(ACCENT)
    c.setFont("Body-Bold", 14)
    c.drawString(MARGIN + 5 * mm, y - 12 * mm, "1. Базовый поиск")
    lines = [
        "Клиент пишет: что нужно, куда везти, объём.",
        "Находим лучших поставщиков по нише.",
        "Показываем список и почему они в топе.",
        "Цены чужих КП не показываем.",
        "Можно дать коридор рынка без обещания сделки.",
        "Оплата: подписка или пакеты поисков.",
    ]
    yy = y - 28 * mm
    gap = (card_h - 40 * mm) / max(len(lines), 1)
    for line in lines:
        bullet(c, MARGIN + 4 * mm, yy, line, w - 8 * mm, size=12, leading=15)
        yy -= gap

    card(c, MARGIN + w + 3 * mm, y, w, card_h, True)
    c.setFillColor(OK)
    c.setFont("Body-Bold", 14)
    c.drawString(MARGIN + w + 8 * mm, y - 12 * mm, "2. Под ключ")
    lines2 = [
        "Только если клиент явно просит.",
        "Сами пишем запросы на производство.",
        "Сами собираем ответы и сравниваем.",
        "Сами уточняем сроки, оплату, доставку.",
        "Отдаём сводку: кому и на каких условиях.",
        "Оплата отдельно (фикс и/или доля экономии).",
    ]
    yy = y - 28 * mm
    for line in lines2:
        bullet(c, MARGIN + w + 7 * mm, yy, line, w - 8 * mm, size=12, leading=15)
        yy -= gap
    footer(c)


def p_market(c, ch):
    header(c, "Рынок: где играем", 4)
    y = TOP
    w = (CW - 4 * mm) / 3
    stat(c, MARGIN, y, w, 28 * mm, "~360 млрд ₽", "гофра в России, 2024", ACCENT)
    stat(c, MARGIN + w + 2 * mm, y, w, 28 * mm, "1,2–1,43 трлн", "косметика России", ACCENT2)
    stat(c, MARGIN + 2 * (w + 2 * mm), y, w, 28 * mm, "3–5 млрд ₽", "софт закупок (SRM)*", WARN)
    y -= 32 * mm
    img_fit(c, ch["market"], MARGIN, y, CW, 78 * mm)
    y -= 82 * mm
    wrap(
        c,
        "*Оценка сегмента систем управления закупками в РФ ~3–5 млрд ₽ за 2025, рост порядка 25–30%; на 2026 ждут +12–18%. Это фон спроса на цифровые закупки — не наша выручка. Источник: обзоры рынка закупок / SRM (РБК Компании, TAdviser).",
        MARGIN,
        y,
        CW,
        size=9.5,
        leading=12.5,
        color=MUTED,
    )
    y -= 26 * mm
    wrap(
        c,
        "Наш старт уже: косметические компании Москвы, которым регулярно нужны гофрокоробки. Узко — зато быстрее накопить полезную базу и первые оплаты.",
        MARGIN,
        y,
        CW,
        size=11,
        leading=14,
    )
    footer(c)


def p_competitors(c, ch):
    header(c, "С кем сравнивают", 5)
    y = TOP
    img_fit(c, ch["comp"], MARGIN, y, CW, 78 * mm)
    y -= 82 * mm
    table(
        c,
        MARGIN,
        y,
        [36 * mm, 52 * mm, 90 * mm],
        ["Кто", "Что делают", "Чем мы другие"],
        [
            ["ИИ-поиск", "Ищут и шлют запросы", "Не светим чужие цены; «под ключ» отдельно"],
            ["Площадки", "Процедуры закупок", "Помогаем до выбора, не заменяем торги"],
            ["Каталоги", "Типовой товар", "Работаем под партию и условия клиента"],
            ["Excel", "Как сейчас", "Быстрее, база не пропадает"],
        ],
        row_h=11 * mm,
        fs=10,
    )
    footer(c)


def p_edge(c, ch):
    header(c, "За счёт чего выигрываем", 6)
    y = TOP
    points = [
        ("Честность цен", "Не показываем чужие КП и не обещаем чужую цифру как вашу."),
        ("Два режима", "Быстрый список каждый день; глубокое сопровождение — за отдельную плату."),
        ("Узкая ниша", "Гофра для косметики Москвы — быстрее учимся, чем «всем обо всём»."),
        ("Память запросов", "Похожий запрос завтра дешевле: не ищем всё заново."),
        ("Урок после сделки", "Если вели «под ключ», запоминаем: сорвалось или прошло хорошо."),
        ("Сначала база клиента", "Его проверенные поставщики важнее холодного рынка."),
    ]
    for t, d in points:
        card(c, MARGIN, y, CW, 24 * mm, True)
        c.setFillColor(INK)
        c.setFont("Body-Bold", 12)
        c.drawString(MARGIN + 5 * mm, y - 9 * mm, t)
        wrap(c, d, MARGIN + 5 * mm, y - 17 * mm, CW - 10 * mm, size=10.5, leading=13, color=MUTED)
        y -= 26.5 * mm
    footer(c)


def p_demand(c, ch):
    """Demand + AI wind — replaces old traction honesty slide."""
    header(c, "Почему спрос растёт именно сейчас", 7)
    y = TOP
    wrap(
        c,
        "Рынок цифровых закупок в России уже не «игрушка»: компании платят за порядок в снабжении, а ИИ из моды превращается в прикладные задачи — поиск, разбор документов, подсказки.",
        MARGIN,
        y,
        CW,
        size=11,
        leading=14,
    )
    y -= 22 * mm
    img_fit(c, ch["demand"], MARGIN, y, CW, 82 * mm)
    y -= 86 * mm
    table(
        c,
        MARGIN,
        y,
        [52 * mm, 126 * mm],
        ["Факт рынка", "Что это значит для Postavshik"],
        [
            ["SRM ~3–5 млрд ₽", "Деньги на софт закупок уже есть; мы берём узкий кусок — поиск поставщиков"],
            ["Рост ~12–18% (2026)", "Ветер в спину, но не «взрыв»; расти нужно своей нишей"],
            ["ИИ идёт в практику", "Клиенты ждут пользы, не чата; наша модель «без ложных цен» снимает страх"],
            ["Снабженец перегружен", "Готовы платить за экономию часов — если результат понятен"],
        ],
        row_h=12 * mm,
        fs=9.5,
    )
    footer(c)


def p_growth_how(c, ch):
    header(c, "Как вырасти за 3 месяца", 8)
    y = TOP
    img_fit(c, ch["path"], MARGIN, y, CW, 56 * mm)
    y -= 60 * mm
    img_fit(c, ch["funnel"], MARGIN, y, CW, 88 * mm)
    y -= 92 * mm
    wrap(
        c,
        "Базовый путь: ~80 целевых контактов в Москве → ~18 разговоров → ~8 партнёров с базами → ~6 платных подписок и ~4 услуги «под ключ». Без холодного спама всем подряд — только ниша гофры для косметики.",
        MARGIN,
        y,
        CW,
        size=10.5,
        leading=13.5,
        color=MUTED,
    )
    footer(c)


def p_growth_money(c, ch):
    header(c, "Сколько можем заработать за 3 месяца", 9)
    y = TOP
    w = (CW - 4 * mm) / 3
    stat(c, MARGIN, y, w, 26 * mm, "~130 тыс.", "слабый · 90 дней", DANGER)
    stat(c, MARGIN + w + 2 * mm, y, w, 26 * mm, "~465 тыс.", "базовый · 90 дней", ACCENT)
    stat(c, MARGIN + 2 * (w + 2 * mm), y, w, 26 * mm, "~760 тыс.", "сильный · 90 дней", OK)
    y -= 30 * mm
    img_fit(c, ch["rev3m"], MARGIN, y, CW, 78 * mm)
    y -= 82 * mm
    img_fit(c, ch["mix3m"], MARGIN, y, CW, 62 * mm)
    footer(c)


def p_growth_detail(c, ch):
    header(c, "Разбор денег: откуда цифры", 10)
    y = TOP
    table(
        c,
        MARGIN,
        y,
        [28 * mm, 42 * mm, 42 * mm, 66 * mm],
        ["Месяц", "Подписки", "Под ключ", "Что делаем"],
        [
            ["1", "0–2 × 12–15 тыс.", "0–1 × 40 тыс.", "Партнёры, базы, первые пилоты"],
            ["2", "3–6 × 12–15 тыс.", "1–2 × 40–50 тыс.", "Повторы поисков, первые оплаты"],
            ["3", "5–12 × 15 тыс.", "2–3 × 40–60 тыс.", "Кейсы, пакеты, расширение внутри ниши"],
        ],
        row_h=14 * mm,
        fs=9.5,
    )
    y -= 58 * mm
    card(c, MARGIN, y, CW, 52 * mm, True)
    c.setFillColor(INK)
    c.setFont("Body-Bold", 12)
    c.drawString(MARGIN + 5 * mm, y - 11 * mm, "Базовый месяц 3 (пример)")
    wrap(
        c,
        "8 подписок × 15 тыс. = 120 тыс. Плюс 3 услуги «под ключ» × 50 тыс. = 150 тыс. Плюс мелкие пакеты ~30 тыс. Итого ~300 тыс. за месяц. "
        "Расходы месяца ~180–220 тыс. (основатель/подряд, реклама, ИИ, сервисы). Остаток до налогов ~80–120 тыс. "
        "За все 90 дней в базовом сценарии накопительно ~465 тыс. выручки.",
        MARGIN + 5 * mm,
        y - 22 * mm,
        CW - 10 * mm,
        size=10.5,
        leading=13.5,
    )
    y -= 58 * mm
    card(c, MARGIN, y, CW, 42 * mm, True)
    c.setFillColor(WARN)
    c.setFont("Body-Bold", 11)
    c.drawString(MARGIN + 5 * mm, y - 10 * mm, "Честно")
    wrap(
        c,
        "Это не гарантия. Три месяца — короткий срок: многое зависит от скорости доступа к 6–10 компаниям и от того, не будем ли мы раздавать «под ключ» бесплатно. Без дисциплины по затратам даже сильный спрос легко уйдёт в ноль.",
        MARGIN + 5 * mm,
        y - 20 * mm,
        CW - 10 * mm,
        size=10.5,
        leading=13.5,
    )
    footer(c)


def p_costs(c, ch):
    header(c, "Расходы и себестоимость", 11)
    y = TOP
    img_fit(c, ch["pie"], MARGIN, y, 78 * mm, 70 * mm)
    table(
        c,
        MARGIN + 82 * mm,
        y,
        [44 * mm, 52 * mm],
        ["Статья", "В месяц*"],
        [
            ["Люди / подряд", "80–250 тыс."],
            ["Продажи", "30–120 тыс."],
            ["ИИ и поиск", "15–80 тыс."],
            ["Серверы", "10–40 тыс."],
            ["Бух/налоги", "15–60 тыс."],
            ["Итого", "150–550 тыс."],
        ],
        row_h=10 * mm,
        fs=10,
    )
    y -= 78 * mm
    wrap(c, "*На старте ближе к низу диапазона. Растёт вместе с продажами.", MARGIN, y, CW, size=9.5, leading=12, color=MUTED)
    y -= 10 * mm
    img_fit(c, ch["ucost"], MARGIN, y, CW, 68 * mm)
    y -= 74 * mm
    wrap(
        c,
        "Обычный поиск должен быть дешёвым. Дорогая ручная работа — только в «под ключ», где клиент платит отдельно.",
        MARGIN,
        y,
        CW,
        size=11,
        leading=14,
        color=MUTED,
    )
    footer(c)


def p_year(c, ch):
    header(c, "Если 3 месяца удались — год", 12)
    y = TOP
    img_fit(c, ch["pnl"], MARGIN, y, CW, 78 * mm)
    y -= 84 * mm
    table(
        c,
        MARGIN,
        y,
        [32 * mm, 38 * mm, 38 * mm, 32 * mm, 38 * mm],
        ["Сценарий", "Выручка", "Расходы", "Итог", "Условие"],
        [
            ["Слабый", "0,6 млн", "1,4 млн", "−0,8 млн", "Мало оплат"],
            ["Базовый", "2,4 млн", "2,0 млн", "+0,4 млн", "25–40 клиентов"],
            ["Удачный", "6,0 млн", "3,8 млн", "+2,2 млн", "Плотная ниша"],
        ],
        row_h=12 * mm,
        fs=10,
    )
    y -= 54 * mm
    wrap(
        c,
        "Год строится из повторов в нише + доли «под ключ». Если за 90 дней нет 4–6 платящих — годовые цифры нереалистичны.",
        MARGIN,
        y,
        CW,
        size=11,
        leading=14,
        color=MUTED,
    )
    footer(c)


def p_plan90(c, ch):
    header(c, "План на 90 дней", 13)
    y = TOP
    img_fit(c, ch["gtm"], MARGIN, y, CW, 42 * mm)
    y -= 46 * mm
    phases = [
        ("Дни 1–30", "Двери", "6–10 компаний; базы поставщиков; согласие на обезличенный опыт"),
        ("Дни 31–60", "Плотность", "Частые запросы по коробкам; списки без чужих цен; 2–3 «под ключ» за деньги"),
        ("Дни 61–90", "Деньги", "Показать экономию часов; подписки/пакеты; не расползаться в другие товары"),
    ]
    for a, b, d in phases:
        card(c, MARGIN, y, CW, 28 * mm, True)
        c.setFillColor(ACCENT)
        c.setFont("Body-Bold", 11)
        c.drawString(MARGIN + 5 * mm, y - 9 * mm, a)
        c.setFillColor(INK)
        c.setFont("Body-Bold", 11)
        c.drawString(MARGIN + 32 * mm, y - 9 * mm, b)
        wrap(c, d, MARGIN + 5 * mm, y - 18 * mm, CW - 10 * mm, size=10.5, leading=13, color=MUTED)
        y -= 31 * mm
    footer(c)


def p_risks_close(c, ch):
    header(c, "Риски и итог", 14)
    y = TOP
    img_fit(c, ch["risks"], MARGIN, y, CW, 95 * mm)
    y -= 100 * mm
    card(c, MARGIN, y, CW, 48 * mm, True)
    wrap(
        c,
        "Postavshik — поиск поставщиков без обмана ожиданиями и отдельная услуга под ключ. "
        "Старт: гофра для косметики Москвы. За 3 месяца реалистичная цель в базовом сценарии — около 0,5 млн ₽ выручки при жёсткой воронке и платных «под ключ». "
        "Это модель для разговора, не гарантия. ИП Чебан · август 2026.",
        MARGIN + 5 * mm,
        y - 12 * mm,
        CW - 10 * mm,
        size=11,
        leading=14.5,
    )
    footer(c)


def main():
    ch = {
        "two": chart_two_products(),
        "market": chart_market(),
        "demand": chart_demand(),
        "funnel": chart_funnel_3m(),
        "rev3m": chart_revenue_3m(),
        "mix3m": chart_mix_3m(),
        "path": chart_path_how(),
        "pnl": chart_pnl_year(),
        "pie": chart_costs(),
        "ucost": chart_unit_cost(),
        "comp": chart_competitors(),
        "risks": chart_risks(),
        "gtm": chart_gtm(),
    }
    c = canvas.Canvas(str(OUT), pagesize=A4)
    pages = [
        p_cover,
        p_problem,
        p_products,
        p_market,
        p_competitors,
        p_edge,
        p_demand,
        p_growth_how,
        p_growth_money,
        p_growth_detail,
        p_costs,
        p_year,
        p_plan90,
        p_risks_close,
    ]
    assert len(pages) == TOTAL
    for i, fn in enumerate(pages):
        if i:
            c.showPage()
        fn(c, ch)
    c.save()
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
