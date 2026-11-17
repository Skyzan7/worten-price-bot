"""Recolha de produtos e preços das páginas públicas da Worten.

Não há API pública gratuita da Worten, por isso lemos as páginas
como um browser e extraímos os dados estruturados que vêm no HTML:
  1. blocos JSON-LD (schema.org Product / ItemList / Offer)
  2. JSON embebido em <script> (estado da app: __NEXT_DATA__, etc.)
O extrator é genérico: procura objetos com nome + preço, por isso
aguenta pequenas mudanças no site sem ter de reescrever seletores.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

log = logging.getLogger("scraper")
BASE = "https://www.worten.pt"

try:  # curl_cffi imita a impressão digital TLS do Chrome (menos bloqueios)
    from curl_cffi import requests as http

    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # pragma: no cover
    import requests as http  # type: ignore

    _IMPERSONATE = {}

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


@dataclass
class Product:
    pid: str
    name: str
    price: float
    url: str
    old_price: float | None = None
    seller: str | None = None


# ───────────────────────── utilitários ─────────────────────────

def parse_price(v) -> float | None:
    """Converte 1299.99 / "1.299,99 €" / {"value": 12} / "129999" (cêntimos?) em float."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, dict):
        for k in ("value", "amount", "price", "current", "centAmount"):
            if k in v:
                p = parse_price(v[k])
                if p is not None and k == "centAmount":
                    p /= 100
                return p
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    if isinstance(v, str):
        s = re.sub(r"[^\d,.\-]", "", v)
        if not s:
            return None
        if "," in s and "." in s:  # 1.299,99  ou  1,299.99
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            f = float(s)
            return f if f > 0 else None
        except ValueError:
            return None
    return None


NAME_KEYS = ("name", "title", "productName", "displayName")
PRICE_KEYS = ("finalPrice", "salePrice", "currentPrice", "sellingPrice",
              "priceWithDiscount", "price", "lowPrice")
OLD_KEYS = ("originalPrice", "oldPrice", "listPrice", "previousPrice",
            "regularPrice", "priceBefore", "referencePrice", "crossedPrice",
            "highPrice")
ID_KEYS = ("sku", "productId", "ean", "gtin13", "gtin", "mpn", "id", "code")
URL_KEYS = ("url", "link", "href", "productUrl", "slug", "path")


def _first(d: dict, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _abs_url(u) -> str | None:
    if not isinstance(u, str) or not u:
        return None
    if u.startswith("http"):
        return u
    return urljoin(BASE, u if u.startswith("/") else "/" + u)


def _product_from_dict(d: dict) -> Product | None:
    name = _first(d, NAME_KEYS)
    if not isinstance(name, str) or len(name) < 4:
        return None

    price = parse_price(_first(d, PRICE_KEYS))
    offers = d.get("offers")
    if price is None and offers:  # schema.org Offer / AggregateOffer
        off = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(off, dict):
            price = parse_price(_first(off, PRICE_KEYS))
            d = {**off, **d}
    if price is None:
        return None

    url = _abs_url(_first(d, URL_KEYS))
    if not url or "worten.pt" not in url:
        return None

    pid = _first(d, ID_KEYS)
    pid = str(pid) if pid is not None else url.split("?")[0]
    old = parse_price(_first(d, OLD_KEYS))
    if old is not None and old <= price:
        old = None
    seller = d.get("seller")
    if isinstance(seller, dict):
        seller = seller.get("name")
    return Product(pid=pid, name=name.strip(), price=round(price, 2), url=url,
                   old_price=old, seller=seller if isinstance(seller, str) else None)


def _walk(obj, out: dict[str, Product], depth=0):
    if depth > 40:
        return
    if isinstance(obj, dict):
        p = _product_from_dict(obj)
        if p and p.pid not in out:
            out[p.pid] = p
        for v in obj.values():
            _walk(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out, depth + 1)


def extract_products(html: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Product] = {}

    for tag in soup.find_all("script"):
        txt = (tag.string or tag.get_text() or "").strip()
        if not txt:
            continue
        typ = (tag.get("type") or "").lower()
        data = None
        if "json" in typ or tag.get("id") == "__NEXT_DATA__":
            try:
                data = json.loads(txt)
            except json.JSONDecodeError:
                continue
        else:  # estado embebido: window.__X__ = {...};
            m = re.search(r"=\s*(\{.*\})\s*;?\s*$", txt, re.S)
            if m and len(m.group(1)) > 200:
                try:
                    data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
        if data is not None:
            _walk(data, found)

    return list(found.values())


# ───────────────────────── rede ─────────────────────────

def _page_url(url: str, page: int) -> str:
    if page == 1:
        return url
    parts = urlparse(url)
    q = parse_qs(parts.query)
    q["page"] = [str(page)]
    return urlunparse(parts._replace(query=urlencode(q, doseq=True)))


def fetch(url: str, retries: int = 3) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            r = http.get(url, headers=HEADERS, timeout=30, **_IMPERSONATE)
            if r.status_code == 200:
                return r.text
            log.warning("HTTP %s em %s (tentativa %d)", r.status_code, url, attempt)
        except Exception as e:  # noqa: BLE001
            log.warning("Erro em %s: %s (tentativa %d)", url, e, attempt)
        time.sleep(5 * attempt)
    return None


def scrape(urls: list[str], max_pages: int = 3, delay=(3, 7),
           debug_dir: str = "data/debug") -> tuple[list[Product], list[str]]:
    """Devolve (produtos, erros)."""
    products: dict[str, Product] = {}
    errors: list[str] = []
    for base_url in urls:
        prev_ids: set[str] = set()
        for page in range(1, max_pages + 1):
            u = _page_url(base_url, page)
            html = fetch(u)
            if html is None:
                errors.append(f"Falhou: {u}")
                break
            items = extract_products(html)
            if not items:
                if page == 1:
                    Path(debug_dir).mkdir(parents=True, exist_ok=True)
                    fn = Path(debug_dir) / (re.sub(r"\W+", "_", u)[-80:] + ".html")
                    fn.write_text(html, encoding="utf-8")
                    errors.append(f"0 produtos em {u} (HTML guardado em {fn})")
                break
            ids = {p.pid for p in items}
            if ids == prev_ids:  # paginação não avançou
                break
            prev_ids = ids
            for p in items:
                products.setdefault(p.pid, p)
            log.info("%s → %d produtos", u, len(items))
            time.sleep(random.uniform(*delay))
    return list(products.values()), errors
