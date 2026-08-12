from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import Contract, ScrapeRun, Supplier, Tender
from app.parsers.contracts import ParsedContract, get_contract_parsers
from app.services.customers import extract_inn, extract_kpp
from app.services.normalize import extract_okpd2, normalize_price, normalize_region, normalize_text


def _normalize_name(name: str | None) -> str:
    base = normalize_text(name) or (name or "").strip()
    return re.sub(r"\s+", " ", base).lower()[:512]


def _discount_pct(nmck: float | None, price: float | None) -> float | None:
    if nmck is None or price is None or nmck <= 0:
        return None
    return round((nmck - price) / nmck * 100.0, 2)


def _search_blob(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).casefold()


def upsert_supplier(
    db: Session,
    *,
    name: str | None,
    inn: str | None,
    kpp: str | None = None,
    region: str | None = None,
) -> Supplier | None:
    inn_clean = (inn or "").strip() or None
    name_clean = normalize_text(name) or (name or "").strip()
    if not inn_clean and not name_clean:
        return None

    supplier: Supplier | None = None
    if inn_clean:
        supplier = db.query(Supplier).filter(Supplier.inn == inn_clean).first()
    if supplier is None and name_clean:
        norm = _normalize_name(name_clean)
        supplier = db.query(Supplier).filter(Supplier.name_normalized == norm).first()

    if supplier is None:
        supplier = Supplier(
            inn=inn_clean,
            kpp=kpp,
            name=name_clean or f"ИНН {inn_clean}",
            name_normalized=_normalize_name(name_clean or inn_clean or "unknown"),
            region=region,
        )
        db.add(supplier)
        db.flush()
        return supplier

    if name_clean and (not supplier.name or len(name_clean) > len(supplier.name)):
        supplier.name = name_clean
        supplier.name_normalized = _normalize_name(name_clean)
    if inn_clean and not supplier.inn:
        supplier.inn = inn_clean
    if kpp and not supplier.kpp:
        supplier.kpp = kpp
    if region and not supplier.region:
        supplier.region = region
    return supplier


def _recompute_supplier_stats(db: Session, supplier_id: int) -> None:
    rows = (
        db.query(Contract.price, Contract.discount_pct, Contract.signed_at)
        .filter(Contract.supplier_id == supplier_id, Contract.price.isnot(None))
        .all()
    )
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        return
    prices = [r[0] for r in rows if r[0] is not None]
    discounts = [r[1] for r in rows if r[1] is not None]
    dates = [r[2] for r in rows if r[2] is not None]
    supplier.win_count = len(rows)
    supplier.total_contract_price = float(sum(prices)) if prices else 0.0
    supplier.avg_contract_price = float(sum(prices) / len(prices)) if prices else None
    supplier.avg_discount_pct = float(sum(discounts) / len(discounts)) if discounts else None
    supplier.last_won_at = max(dates) if dates else None


def _link_tender(db: Session, contract: Contract) -> None:
    if contract.tender_id:
        return
    if not contract.purchase_number:
        return
    tender = (
        db.query(Tender)
        .filter(
            or_(
                Tender.external_id == contract.purchase_number,
                Tender.external_id.like(f"%{contract.purchase_number}%"),
            )
        )
        .order_by(Tender.id.desc())
        .first()
    )
    if tender:
        contract.tender_id = tender.id
        if contract.nmck is None and tender.price is not None:
            contract.nmck = tender.price
            contract.discount_pct = _discount_pct(contract.nmck, contract.price)


def upsert_contracts(db: Session, items: list[ParsedContract]) -> tuple[int, int]:
    """Returns (upserted, skipped)."""
    upserted = 0
    skipped = 0
    touched_suppliers: set[int] = set()

    for item in items:
        if not item.external_id or not item.title or not item.url:
            skipped += 1
            continue

        title = normalize_text(item.title) or item.title
        price = normalize_price(item.price)
        nmck = normalize_price(item.nmck)
        region = normalize_region(item.region)
        supplier_name = normalize_text(item.supplier_name) or item.supplier_name
        customer = normalize_text(item.customer) or item.customer
        okpd2 = item.okpd2 or extract_okpd2(item.description) or extract_okpd2(title)
        supplier_inn = item.supplier_inn or extract_inn(supplier_name) or extract_inn(item.description)
        customer_inn = item.customer_inn or extract_inn(customer) or extract_inn(item.description)
        supplier_kpp = extract_kpp(supplier_name or "") or extract_kpp(item.description or "")

        existing = (
            db.query(Contract)
            .filter(Contract.source == item.source, Contract.external_id == item.external_id)
            .first()
        )
        if existing is None:
            contract = Contract(
                external_id=item.external_id,
                source=item.source,
                law=item.law,
                purchase_number=item.purchase_number,
                title=title,
                customer=customer,
                customer_inn=customer_inn,
                supplier_name=supplier_name,
                supplier_inn=supplier_inn,
                region=region,
                price=price,
                nmck=nmck,
                discount_pct=_discount_pct(nmck, price),
                currency=item.currency or "RUB",
                status=item.status,
                okpd2=okpd2,
                url=item.url,
                description=(item.description or "")[:4000] or None,
                search_text=_search_blob(
                    title, supplier_name, customer, item.description, okpd2, item.purchase_number, supplier_inn
                ),
                signed_at=item.signed_at or item.published_at,
                published_at=item.published_at or item.signed_at,
            )
            db.add(contract)
            db.flush()
        else:
            contract = existing
            contract.title = title or contract.title
            contract.customer = customer or contract.customer
            contract.customer_inn = customer_inn or contract.customer_inn
            contract.supplier_name = supplier_name or contract.supplier_name
            contract.supplier_inn = supplier_inn or contract.supplier_inn
            contract.region = region or contract.region
            if price is not None:
                contract.price = price
            if nmck is not None:
                contract.nmck = nmck
            contract.discount_pct = _discount_pct(contract.nmck, contract.price)
            contract.okpd2 = okpd2 or contract.okpd2
            contract.status = item.status or contract.status
            contract.url = item.url or contract.url
            if item.description:
                contract.description = item.description[:4000]
            contract.signed_at = item.signed_at or item.published_at or contract.signed_at
            contract.published_at = item.published_at or item.signed_at or contract.published_at
            contract.purchase_number = item.purchase_number or contract.purchase_number
            contract.law = item.law or contract.law
            contract.search_text = _search_blob(
                contract.title,
                contract.supplier_name,
                contract.customer,
                contract.description,
                contract.okpd2,
                contract.purchase_number,
                contract.supplier_inn,
            )

        supplier = upsert_supplier(
            db,
            name=contract.supplier_name,
            inn=contract.supplier_inn,
            kpp=supplier_kpp,
            region=contract.region,
        )
        if supplier:
            contract.supplier_id = supplier.id
            touched_suppliers.add(supplier.id)

        _link_tender(db, contract)
        upserted += 1

    for sid in touched_suppliers:
        _recompute_supplier_stats(db, sid)

    db.commit()
    return upserted, skipped


async def run_contract_scrape(
    db: Session | None = None,
    *,
    search_string: str | None = None,
    laws: list[str] | None = None,
) -> list[ScrapeRun]:
    from app.database import SessionLocal

    owns = db is None
    if owns:
        db = SessionLocal()
    assert db is not None
    runs: list[ScrapeRun] = []
    try:
        parsers = get_contract_parsers()
        if laws:
            wanted = {str(x).replace("-ФЗ", "") for x in laws}
            parsers = [p for p in parsers if p.law in wanted]
        for parser in parsers:
            started = datetime.now(timezone.utc)
            run = ScrapeRun(source=parser.source, status="running", started_at=started)
            db.add(run)
            db.commit()
            db.refresh(run)
            try:
                items = await parser.fetch(search_string=search_string)
                upserted, skipped = upsert_contracts(db, items)
                run.fetched = len(items)
                run.upserted = upserted
                run.skipped = skipped
                run.status = "ok" if items else "empty"
                if not items and parser.last_fetch_note:
                    run.error = parser.last_fetch_note
                    run.status = "error"
            except Exception as exc:  # noqa: BLE001
                run.status = "error"
                run.error = str(exc)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(run)
            runs.append(run)
        # Bootstrap shared market cache from fresh contracts (token-free)
        try:
            from app.services.market_cache import ingest_contracts_into_cache

            ingest_contracts_into_cache(db, limit=150)
        except Exception:  # noqa: BLE001
            db.rollback()
        return runs
    finally:
        if owns:
            db.close()


def apply_contract_filters(
    query,
    *,
    q: str | None = None,
    law: str | None = None,
    region: str | None = None,
    okpd2: str | None = None,
    supplier_inn: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    signed_from: datetime | None = None,
    signed_to: datetime | None = None,
):
    if q:
        like = f"%{q.strip().casefold()}%"
        query = query.filter(Contract.search_text.like(like))
    if law:
        query = query.filter(Contract.law.ilike(f"%{law.replace('-ФЗ', '')}%"))
    if region:
        query = query.filter(Contract.region.ilike(f"%{region}%"))
    if okpd2:
        query = query.filter(Contract.okpd2.ilike(f"{okpd2}%"))
    if supplier_inn:
        query = query.filter(Contract.supplier_inn == supplier_inn.strip())
    if min_price is not None:
        query = query.filter(Contract.price >= min_price)
    if max_price is not None:
        query = query.filter(Contract.price <= max_price)
    if signed_from is not None:
        query = query.filter(Contract.signed_at >= signed_from)
    if signed_to is not None:
        query = query.filter(Contract.signed_at <= signed_to)
    return query


def contract_price_stats(db: Session, *, q: str | None = None, okpd2: str | None = None, region: str | None = None) -> dict:
    query = apply_contract_filters(db.query(Contract), q=q, okpd2=okpd2, region=region)
    prices = [p for (p,) in query.filter(Contract.price.isnot(None)).with_entities(Contract.price).limit(5000).all()]
    discounts = [
        d
        for (d,) in apply_contract_filters(db.query(Contract), q=q, okpd2=okpd2, region=region)
        .filter(Contract.discount_pct.isnot(None))
        .with_entities(Contract.discount_pct)
        .limit(5000)
        .all()
    ]
    if not prices:
        return {
            "count": 0,
            "median_price": None,
            "avg_price": None,
            "p25_price": None,
            "p75_price": None,
            "avg_discount_pct": None,
        }
    prices_sorted = sorted(prices)
    n = len(prices_sorted)

    def _pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round((p / 100.0) * (n - 1)))))
        return float(prices_sorted[idx])

    return {
        "count": n,
        "median_price": float(median(prices_sorted)),
        "avg_price": float(sum(prices_sorted) / n),
        "p25_price": _pct(25),
        "p75_price": _pct(75),
        "avg_discount_pct": float(sum(discounts) / len(discounts)) if discounts else None,
    }


def top_suppliers_by_wins(
    db: Session,
    *,
    q: str | None = None,
    okpd2: str | None = None,
    region: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Aggregate winners from filtered contracts (not global supplier table alone)."""
    query = apply_contract_filters(db.query(Contract), q=q, okpd2=okpd2, region=region)
    query = query.filter(or_(Contract.supplier_inn.isnot(None), Contract.supplier_name.isnot(None)))
    rows = (
        query.with_entities(
            Contract.supplier_inn,
            Contract.supplier_name,
            func.count(Contract.id),
            func.avg(Contract.price),
            func.avg(Contract.discount_pct),
            func.sum(Contract.price),
            func.max(Contract.signed_at),
        )
        .group_by(Contract.supplier_inn, Contract.supplier_name)
        .order_by(func.count(Contract.id).desc())
        .limit(limit)
        .all()
    )
    out: list[dict] = []
    for inn, name, wins, avg_price, avg_disc, total, last_won in rows:
        out.append(
            {
                "supplier_inn": inn,
                "supplier_name": name,
                "wins": int(wins or 0),
                "avg_price": float(avg_price) if avg_price is not None else None,
                "avg_discount_pct": float(avg_disc) if avg_disc is not None else None,
                "total_price": float(total) if total is not None else None,
                "last_won_at": last_won,
            }
        )
    return out


def seed_contracts_if_empty(db: Session) -> int:
    if db.query(Contract.id).first():
        return 0
    now = datetime.now(timezone.utc)
    samples = [
        ("Полиэтилен гранулированный HDPE", "ООО «ПолимерСнаб»", "7701234567", 2_700_000, 3_100_000, "22.21"),
        ("Картон гофрированный для упаковки", "ООО «УпакПром»", "7812345678", 980_000, 1_150_000, "17.21"),
        ("Перевозка грузов рефрижератором", "ООО «ХолодТранс»", "5409876543", 1_450_000, 1_800_000, "49.41"),
        ("Поставка краски промышленной", "АО «ЛакоКраска»", "5001122334", 620_000, 700_000, "20.30"),
        ("Комплектующие для оборудования", "ООО «ТехноДеталь»", "6677889900", 3_200_000, 3_900_000, "28.15"),
        ("Пленка полиэтиленовая рукав", "ООО «ПолимерСнаб»", "7701234567", 410_000, 480_000, "22.21"),
        ("Гофроящики под косметику", "ООО «УпакПром»", "7812345678", 760_000, 890_000, "17.21"),
        ("Автоперевозка сборных грузов", "ООО «ХолодТранс»", "5409876543", 890_000, 1_050_000, "49.41"),
    ]
    customers = [
        ("АО «Производство Космо»", "7700111223"),
        ("ООО «СнабРегион»", "7811002233"),
        ("ГБУ «Комбинат»", "7700555666"),
    ]
    items: list[ParsedContract] = []
    for i, (title, supplier, sinn, price, nmck, okpd) in enumerate(samples):
        cust_name, cinn = customers[i % len(customers)]
        items.append(
            ParsedContract(
                external_id=f"SEED-{1000 + i}",
                source="eis_contract_44",
                law="44-ФЗ",
                purchase_number=f"0123456789{i:06d}",
                title=title,
                url=f"https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=SEED-{1000 + i}",
                customer=cust_name,
                customer_inn=cinn,
                supplier_name=supplier,
                supplier_inn=sinn,
                region=["Москва", "Санкт-Петербург", "Новосибирская область"][i % 3],
                price=price,
                nmck=nmck,
                okpd2=okpd,
                status="Исполнение",
                description=f"Демо-контракт: {title}",
                signed_at=now - timedelta(days=7 * (i + 1)),
                published_at=now - timedelta(days=7 * (i + 1)),
            )
        )
    upserted, _ = upsert_contracts(db, items)
    return upserted
