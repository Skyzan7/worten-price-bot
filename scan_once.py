"""Faz UM scan e envia os alertas — para usar com cron ou GitHub Actions
(sem ter um processo sempre ligado)."""
import json
import logging
import os
import urllib.parse
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import core
from storage import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def send(token: str, chat: str, text: str):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)


def main():
    token, chat = core.env("TELEGRAM_TOKEN"), core.env("TELEGRAM_CHAT_ID")
    cfg = core.load_config()
    store = Store(cfg["db_path"])
    store.seed_urls(cfg["watch_urls"])
    alerts, n, errors = core.run_scan(cfg, store)
    for a in alerts[:25]:
        send(token, chat, core.format_alert(a))
    if n == 0 and errors:
        send(token, chat, "⚠️ Scan sem produtos:\n" + "\n".join(errors[:8]))
    print(json.dumps({"produtos": n, "alertas": len(alerts), "erros": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
