from __future__ import annotations

import re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import certifi
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Tender
from app.services.normalize import extract_okpd2, normalize_price, normalize_text


def _ssl_verify() -> bool | str:
    if not settings.http_verify_ssl:
        return False
    return certifi.where()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = date_parser.parse(value, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, OverflowError):
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(root: ET.Element, names: tuple[str, ...]) -> str | None:
    wanted = {n.lower() for n in names}
    for el in root.iter():
        if _local(el.tag).lower() in wanted and (el.text or "").strip():
            return el.text.strip()
    return None


def _collect_documents(root: ET.Element) -> list[dict]:
    docs: list[dict] = []
    for el in root.iter():
        if _local(el.tag).lower() not in {"attachment", "document", "doc"}:
            continue
        name = None
        url = None
        for child in list(el):
            tag = _local(child.tag).lower()
            if tag in {"filename", "fileName", "name", "docName".lower()} and child.text:
                name = child.text.strip()
            if tag in {"url", "href", "content"} and child.text and child.text.startswith("http"):
                url = child.text.strip()
        if name or url:
            docs.append({"name": name or "Документ", "url": url})
    # de-dupe
    seen: set[str] = set()
    unique: list[dict] = []
    for d in docs:
        key = f"{d.get('name')}|{d.get('url')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique[:30]


def _collect_lots(root: ET.Element) -> list[dict]:
    lots: list[dict] = []
    for el in root.iter():
        if _local(el.tag).lower() not in {"lot", "notificationinfo", "purchaseobject"}:
            continue
        name = _find_text(el, ("lotName", "name", "purchaseObjectName", "subject"))
        price_raw = _find_text(el, ("price", "maxPrice", "lotPrice", "amount"))
        okpd = _find_text(el, ("OKPD2", "okpd2", "code"))
        if not name and not price_raw:
            continue
        price = None
        if price_raw:
            cleaned = re.sub(r"[^\d.,]", "", price_raw.replace(" ", "").replace("\xa0", "")).replace(",", ".")
            try:
                price = float(cleaned)
            except ValueError:
                price = None
        lots.append(
            {
                "name": name or "Лот",
                "price": normalize_price(price),
                "okpd2": okpd,
            }
        )
    # Prefer explicit lots; limit noise
    return lots[:20]


async def enrich_tender(db: Session, tender: Tender, force: bool = False) -> Tender:
    if tender.enriched_at and not force and (tender.documents or tender.lots or tender.customer_inn):
        return tender

    if "zakupki.gov.ru" not in (tender.url or "") and not tender.source.startswith("zakupki"):
        tender.enriched_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(tender)
        return tender

    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "application/xml,text/xml,text/html,*/*",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    xml_url = (
        "https://zakupki.gov.ru/epz/order/notice/printForm/viewXml.html"
        f"?regNumber={tender.external_id}"
    )
    html_url = tender.url

    from app.services.http_client import get_client

    client = get_client()
    xml_text = None
    try:
        resp = await client.get(xml_url, headers=headers)
        if resp.status_code == 200 and "<" in resp.text[:200]:
            xml_text = resp.text
    except httpx.HTTPError:
        xml_text = None

    if xml_text:
        try:
            root = ET.fromstring(xml_text)
            customer = _find_text(root, ("fullName", "organizationName", "customerName"))
            inn = _find_text(root, ("INN", "inn"))
            region = _find_text(root, ("region", "kladrRegion", "deliveryPlace"))
            method = _find_text(root, ("placingWayName", "placingWay", "method"))
            status = _find_text(root, ("stage", "status", "purchaseStage"))
            deadline = _find_text(
                root,
                ("collectingEndDT", "submissionCloseDateTime", "endDT", "applicationDeadline"),
            )
            price_raw = _find_text(root, ("maxPrice", "price", "totalPrice"))
            okpd = _find_text(root, ("OKPD2", "okpd2"))
            desc = _find_text(root, ("purchaseObjectInfo", "subject", "hrefName"))

            if customer:
                tender.customer = normalize_text(customer) or tender.customer
            if inn:
                tender.customer_inn = inn
            if region:
                from app.services.normalize import normalize_region

                tender.region = normalize_region(region) or tender.region
            if method:
                tender.method = normalize_text(method) or tender.method
            if status:
                tender.status = normalize_text(status) or tender.status
            if deadline:
                tender.deadline_at = _parse_dt(deadline) or tender.deadline_at
            if price_raw:
                cleaned = re.sub(r"[^\d.,]", "", price_raw.replace(" ", "")).replace(",", ".")
                try:
                    tender.price = normalize_price(float(cleaned)) or tender.price
                except ValueError:
                    pass
            if okpd:
                tender.okpd2 = okpd
            elif not tender.okpd2:
                tender.okpd2 = extract_okpd2(desc) or extract_okpd2(tender.description)
            if desc and not tender.description:
                tender.description = normalize_text(desc)
            tender.documents = _collect_documents(root) or tender.documents or []
            tender.lots = _collect_lots(root) or tender.lots or []
        except ET.ParseError:
            pass

    if not tender.documents:
        try:
            page = await client.get(html_url, headers=headers)
            if page.status_code == 200:
                soup = BeautifulSoup(page.text, "lxml")
                docs = []
                for a in soup.select("a[href*='download'], a[href*='document'], a[href*='file']")[:20]:
                    href = a.get("href") or ""
                    if href.startswith("/"):
                        href = "https://zakupki.gov.ru" + href
                    name = a.get_text(" ", strip=True) or "Документ"
                    if href:
                        docs.append({"name": name[:200], "url": href})
                if docs:
                    tender.documents = docs
                if not tender.okpd2:
                    tender.okpd2 = extract_okpd2(soup.get_text(" ", strip=True))
        except httpx.HTTPError:
            pass

    tender.enriched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tender)
    return tender
