"""Um scan completo: recolher → comparar com histórico → gerar alertas."""
from __future__ import annotations

import html
import logging
import os
from pathlib import Path

import yaml

import detector
import scraper
from storage import Store

log = logging.getLogger("core")
ROOT = Path(__file__).parent


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["db_path"] = str(ROOT / cfg["db_path"])
    return cfg


def run_scan(cfg: dict, store: Store):
    """Devolve (alertas, n_produtos, erros)."""
    urls = store.urls()
    products, errors = scraper.scrape(
        urls, cfg["max_pages_per_url"], (cfg["delay_min_s"], cfg["delay_max_s"]),
        debug_dir=str(ROOT / "data/debug"))

    alerts = []
    rules = cfg["rules"]
    for p in products:
        median, n = store.median(p.pid)          # histórico ANTES desta leitura
        a = detector.check(p, median, n, rules)
        store.record(p)
        if a and not store.recently_alerted(p.pid, p.price, rules["realert_after_hours"]):
            store.mark_alerted(p.pid, p.price)
            alerts.append(a)
    store.log_scan(len(products), len(alerts), len(errors))
    store.commit()
    alerts.sort(key=lambda a: a.score, reverse=True)
    log.info("Scan: %d produtos, %d alertas, %d erros", len(products), len(alerts), len(errors))
    return alerts, len(products), errors


def format_alert(a: detector.Alert) -> str:
    p = a.product
    emoji = "🚨" if (a.drop_pct or 0) >= 70 else "⚠️"
    lines = [
        f"{emoji} <b>Possível falha de preço</b>",
        f"<b>{html.escape(p.name)}</b>",
        f"💶 <b>{p.price:.2f} €</b>" + (f"  (ref. {a.reference:.2f} €)" if a.reference else ""),
    ]
    if p.seller:
        lines.append(f"🏪 Vendedor: {html.escape(p.seller)}")
    lines += [f"• {html.escape(r)}" for r in a.reasons]
    lines.append(f'🔗 <a href="{html.escape(p.url)}">Abrir na Worten</a>')
    return "\n".join(lines)


def env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Falta a variável de ambiente {name} (ver .env.example)")
    return v
