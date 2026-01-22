import os
import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)
from flask import Flask
from threading import Thread

# ===============================
# CONFIG
# ===============================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# TEMP: manually add premium users (Telegram user IDs)
PREMIUM_USERS = set()  # e.g. {123456789}

# ===============================
# KEEP ALIVE (for Render)
# ===============================
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "TradeBuddy is running"

def run_web():
    web_app.run(host="0.0.0.0", port=8080)

Thread(target=run_web).start()

# ===============================
# IN-MEMORY STORAGE (MVP)
# ===============================
user_trades = {}      # user_id -> list of trades
trade_counter = {}   # user_id -> last trade id

# ===============================
# STATES
# ===============================
PAIR, DIRECTION, SESSION, RISK, TARGET = range(5)
CLOSE_ID, CLOSE_RESULT, CLOSE_FATE = range(3)

# ===============================
# COMMANDS
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to TradeBuddy\n\n"
        "Your private trading journal.\n\n"
        "Commands:\n"
        "/trade – Log a trade\n"
        "/close – Close a trade\n"
        "/week – Weekly summary\n"
        "/stats – Quick stats\n"
        "/plan – Free vs Pro\n"
    )

# ===============================
# TRADE FLOW
# ===============================
async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pair? (e.g. EURUSD, XAUUSD)")
    return PAIR

async def trade_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pair"] = update.message.text.upper()
    await update.message.reply_text("Direction? (Buy / Sell)")
    return DIRECTION

async def trade_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    direction = update.message.text.capitalize()
    if direction not in ["Buy", "Sell"]:
        await update.message.reply_text("Type Buy or Sell")
        return DIRECTION
    context.user_data["direction"] = direction
    await update.message.reply_text("Session? (London / NY / Asia)")
    return SESSION

async def trade_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = update.message.text.capitalize()
    if session not in ["London", "Ny", "Asia"]:
        await update.message.reply_text("London, NY or Asia only")
        return SESSION
    context.user_data["session"] = session
    await update.message.reply_text("Risk in R? (e.g. 1)")
    return RISK

async def trade_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["risk"] = float(update.message.text)
        await update.message.reply_text("Target in R? (e.g. 3)")
        return TARGET
    except:
        await update.message.reply_text("Enter a number")
        return RISK

async def trade_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        target = float(update.message.text)

        trade_counter[user_id] = trade_counter.get(user_id, 0) + 1
        trade_id = trade_counter[user_id]

        trade = {
            "id": trade_id,
            "pair": context.user_data["pair"],
            "direction": context.user_data["direction"],
            "session": context.user_data["session"],
            "risk": context.user_data["risk"],
            "target": target,
            "result": None,
            "fate": None,
            "opened": datetime.datetime.now()
        }

        user_trades.setdefault(user_id, []).append(trade)

        await update.message.reply_text(
            f"✅ Trade logged\n"
            f"ID: {trade_id}\n"
            f"{trade['pair']} {trade['direction']} | {trade['session']}\n"
            f"Risk {trade['risk']}R → Target {trade['target']}R"
        )
        return ConversationHandler.END
    except:
        await update.message.reply_text("Enter a valid number")
        return TARGET

# ===============================
# CLOSE TRADE
# ===============================
async def close_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    active = [t for t in user_trades.get(user_id, []) if t["result"] is None]
    if not active:
        await update.message.reply_text("No active trades.")
        return ConversationHandler.END

    msg = "Active trades:\n"
    for t in active:
        msg += f"{t['id']} → {t['pair']} {t['direction']}\n"
    msg += "\nEnter trade ID:"
    await update.message.reply_text(msg)
    return CLOSE_ID

async def close_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["close_id"] = int(update.message.text)
        await update.message.reply_text("Result in R? (e.g. +2, -1, 0)")
        return CLOSE_RESULT
    except:
        await update.message.reply_text("Invalid ID")
        return CLOSE_ID

async def close_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["result"] = float(update.message.text)
        await update.message.reply_text(
            "Fate? (Target Hit / Early Close / BE / Stop Loss)"
        )
        return CLOSE_FATE
    except:
        await update.message.reply_text("Enter a number")
        return CLOSE_RESULT

async def close_fate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fate = update.message.text.capitalize()
    user_id = update.message.from_user.id

    for t in user_trades.get(user_id, []):
        if t["id"] == context.user_data["close_id"]:
            t["result"] = context.user_data["result"]
            t["fate"] = fate
            break

    await update.message.reply_text("✅ Trade closed & journaled")
    return ConversationHandler.END

# ===============================
# WEEKLY SUMMARY
# ===============================
async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    trades = user_trades.get(user_id, [])

    if not trades:
        await update.message.reply_text("No trades yet.")
        return

    closed = [t for t in trades if t["result"] is not None]
    net_r = sum(t["result"] for t in closed)

    if user_id in PREMIUM_USERS:
        msg = "📊 Weekly Breakdown (Pro)\n\n"
        msg += f"Trades: {len(trades)}\nNet R: {net_r}\n\n"
        for t in trades:
            msg += (
                f"{t['id']} | {t['pair']} {t['direction']} | "
                f"{t['session']} | Result: {t['result']}R | Fate: {t['fate']}\n"
            )
    else:
        msg = (
            "📊 Weekly Summary\n"
            f"Trades: {len(trades)}\n"
            f"Net R: {net_r}\n\n"
            "🔓 Upgrade to Pro ($2/month) for full breakdown"
        )

    await update.message.reply_text(msg)

# ===============================
# STATS + PLAN
# ===============================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    trades = user_trades.get(user_id, [])
    open_trades = [t for t in trades if t["result"] is None]
    net_r = sum(t["result"] for t in trades if t["result"] is not None)

    await update.message.reply_text(
        f"📈 Stats\nOpen: {len(open_trades)}\nTotal: {len(trades)}\nNet R: {net_r}"
    )

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆓 Free: journaling + basic weekly summary\n\n"
        "💎 Pro ($2/month):\n"
        "- Full breakdown\n"
        "- Session & pair stats\n"
        "- Fate analysis\n"
        "- Unlimited history"
    )

# ===============================
# MAIN
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    trade_conv = ConversationHandler(
        entry_points=[CommandHandler("trade", trade_start)],
        states={
            PAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_pair)],
            DIRECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_direction)],
            SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_session)],
            RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_risk)],
            TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_target)],
        },
        fallbacks=[],
    )

    close_conv = ConversationHandler(
        entry_points=[CommandHandler("close", close_start)],
        states={
            CLOSE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, close_id)],
            CLOSE_RESULT: [MessageHandler(filters.TEXT & ~filters.COMMAND, close_result)],
            CLOSE_FATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, close_fate)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(trade_conv)
    app.add_handler(close_conv)

    print("🤖 TradeBuddy bot running")
    app.run_polling()

if __name__ == "__main__":
    main()
