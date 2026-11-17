"""Bot do Telegram: scan automático de 30 em 30 min + comandos."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import core
from storage import Store

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

CFG = core.load_config()
STORE = Store(CFG["db_path"])
STORE.seed_urls(CFG["watch_urls"])
TOKEN = core.env("TELEGRAM_TOKEN")
CHAT_ID = int(core.env("TELEGRAM_CHAT_ID"))
_scan_lock = asyncio.Lock()


def admin_only(fn):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != CHAT_ID:
            return  # ignora desconhecidos
        return await fn(update, ctx)
    return wrapper


async def do_scan(ctx: ContextTypes.DEFAULT_TYPE, manual: bool = False):
    if _scan_lock.locked():
        if manual:
            await ctx.bot.send_message(CHAT_ID, "⏳ Já está um scan a correr.")
        return
    async with _scan_lock:
        alerts, n, errors = await asyncio.to_thread(core.run_scan, CFG, STORE)
    for a in alerts[:25]:  # limite anti-spam por scan
        await ctx.bot.send_message(CHAT_ID, core.format_alert(a),
                                   parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=False)
        await asyncio.sleep(1)
    if len(alerts) > 25:
        await ctx.bot.send_message(CHAT_ID, f"… e mais {len(alerts) - 25} alertas.")
    if manual or (errors and n == 0):
        msg = f"✅ Scan terminado: {n} produtos, {len(alerts)} alertas."
        if errors:
            msg += "\n⚠️ Problemas:\n" + "\n".join(f"• {e}" for e in errors[:8])
        await ctx.bot.send_message(CHAT_ID, msg)


async def job_scan(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await do_scan(ctx)
    except Exception as e:  # noqa: BLE001
        log.exception("Scan falhou")
        await ctx.bot.send_message(CHAT_ID, f"❌ Scan falhou: {e}")


@admin_only
async def cmd_start(update: Update, ctx):
    await update.message.reply_text(
        "🤖 Bot de falhas de preço Worten\n\n"
        f"Faço scan a cada {CFG['scan_interval_min']} min e aviso-te aqui.\n\n"
        "/scan – scan agora\n/status – estatísticas\n/list – URLs vigiadas\n"
        "/add <url> – vigiar página\n/remove <url> – deixar de vigiar\n"
        "/regras – limites atuais")


@admin_only
async def cmd_scan(update: Update, ctx):
    await update.message.reply_text("🔎 A fazer scan… (pode demorar uns minutos)")
    await do_scan(ctx, manual=True)


@admin_only
async def cmd_status(update: Update, ctx):
    s = STORE.stats()
    last = "nunca"
    if s["last_scan"]:
        ts, np, na, ne = s["last_scan"]
        last = (f"{dt.datetime.fromtimestamp(ts):%d/%m %H:%M} "
                f"({np} produtos, {na} alertas, {ne} erros)")
    nxt = ctx.job_queue.get_jobs_by_name("scan")
    nxt_txt = f"{nxt[0].next_t:%H:%M}" if nxt and nxt[0].next_t else "—"
    await update.message.reply_text(
        f"📊 Produtos seguidos: {s['products']}\n"
        f"📈 Leituras de preço: {s['readings']}\n"
        f"🔔 Alertas (24 h): {s['alerts_24h']}\n"
        f"🕒 Último scan: {last}\n⏭️ Próximo: {nxt_txt}")


@admin_only
async def cmd_list(update: Update, ctx):
    urls = STORE.urls()
    await update.message.reply_text(
        "👀 A vigiar:\n" + "\n".join(f"• {u}" for u in urls) if urls else "Nenhuma URL.",
        disable_web_page_preview=True)


@admin_only
async def cmd_add(update: Update, ctx):
    if not ctx.args or "worten.pt" not in ctx.args[0]:
        return await update.message.reply_text("Uso: /add https://www.worten.pt/...")
    STORE.add_url(ctx.args[0])
    await update.message.reply_text("✅ Adicionado.")


@admin_only
async def cmd_remove(update: Update, ctx):
    if not ctx.args:
        return await update.message.reply_text("Uso: /remove <url>")
    ok = STORE.remove_url(ctx.args[0])
    await update.message.reply_text("🗑️ Removido." if ok else "Não encontrei essa URL.")


@admin_only
async def cmd_rules(update: Update, ctx):
    r = CFG["rules"]
    await update.message.reply_text(
        f"• Queda vs histórico ≥ {r['drop_vs_history_pct']}% "
        f"(após {r['min_history_points']} leituras)\n"
        f"• Desconto vs preço riscado ≥ {r['drop_vs_old_price_pct']}%\n"
        f"• Absurdo: < {r['absurd_price_below']} € em produto ≥ {r['absurd_if_median_above']} €\n"
        f"• Ignora produtos < {r['min_reference_price']} €\n"
        "Edita config.yaml para mudar.")


def main():
    app = Application.builder().token(TOKEN).build()
    for name, fn in [("start", cmd_start), ("help", cmd_start), ("scan", cmd_scan),
                     ("status", cmd_status), ("list", cmd_list), ("add", cmd_add),
                     ("remove", cmd_remove), ("regras", cmd_rules)]:
        app.add_handler(CommandHandler(name, fn))
    app.job_queue.run_repeating(job_scan, interval=CFG["scan_interval_min"] * 60,
                                first=10, name="scan")
    log.info("Bot a correr. Scan a cada %s min.", CFG["scan_interval_min"])
    app.run_polling()


if __name__ == "__main__":
    main()
