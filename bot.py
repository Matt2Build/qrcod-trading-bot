import os
from telegram.ext import Updater, CommandHandler
import requests, pandas as pd, pandas_ta as ta, time

# Use environment variables for secrets
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("COINGECKO_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"
watchlist = []
last_signals = {}

# Validate secrets
if not TELEGRAM_TOKEN or not API_KEY:
    raise ValueError("TELEGRAM_TOKEN and COINGECKO_API_KEY must be set in environment variables")

def start(update, context):
    update.message.reply_text("Hello! I'm your day trading bot. I monitor your watchlist and send signals on threshold crossings.\nCommands:\n/add <coin> - Add to watchlist\n/remove <coin> - Remove from watchlist\n/list - Show watchlist\n/price <coin> - Get live price")

def add(update, context):
    if not context.args: update.message.reply_text("Use /add <coin> e.g., /add bitcoin"); return
    coin = context.args[0].lower()
    if coin in watchlist: update.message.reply_text(f"{coin.upper()} already in watchlist")
    else: watchlist.append(coin); update.message.reply_text(f"Added {coin.upper()}")

def remove(update, context):
    if not context.args: update.message.reply_text("Use /remove <coin> e.g., /remove bitcoin"); return
    coin = context.args[0].lower()
    if coin not in watchlist: update.message.reply_text(f"{coin.upper()} not in watchlist")
    else: watchlist.remove(coin); update.message.reply_text(f"Removed {coin.upper()}")

def list_coins(update, context): update.message.reply_text("Watchlist:\n" + "\n".join([coin.upper() for coin in watchlist]) if watchlist else "Watchlist empty. Use /add.")

def get_price(update, context):
    if not context.args: update.message.reply_text("Use /price <coin> e.g., /price bitcoin"); return
    coin = context.args[0].lower()
    try:
        response = requests.get(f"{BASE_URL}/simple/price?ids={coin}&vs_currencies=usd&x_cg_demo_api_key={API_KEY}")
        data = response.json()
        price = data[coin]["usd"] if coin in data and "usd" in data[coin] else None
        update.message.reply_text(f"Live price of {coin.upper()} is ${price:.2f} USD" if price else f"Invalid coin ID for {coin.upper()}")
    except: update.message.reply_text(f"Error fetching price for {coin.upper()}")

def fetch_price_data(coin):
    try:
        response = requests.get(f"{BASE_URL}/coins/{coin}/ohlc?vs_currency=usd&days=1&interval=5m&x_cg_demo_api_key={API_KEY}")
        data = response.json()
        if not data or "status" in data: return None
        return pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"]).assign(timestamp=lambda x: pd.to_datetime(x["timestamp"], unit="ms"))
    except Exception as e: print(f"Error: {e}"); return None

def generate_signal(coin):
    df = fetch_price_data(coin)
    if df is None or len(df) < 50: return None, None
    df["rsi"] = ta.rsi(df["close"], 14); macd = ta.macd(df["close"]); df["macd"], df["macd_signal"] = macd["MACD_12_26_9"], macd["MACDs_12_26_9"]
    df["sma10"], df["sma50"] = ta.sma(df["close"], 10), ta.sma(df["close"], 50)
    df["ema10"], df["ema50"] = ta.ema(df["close"], 10), ta.ema(df["close"], 50)
    bb = ta.bbands(df["close"], 20); df["bb_upper"], df["bb_lower"] = bb["BBU_20_2.0"], bb["BBL_20_2.0"]
    stoch = ta.stoch(df["high"], df["low"], df["close"]); df["stoch_k"] = stoch["STOCHk_14_3_3"]
    df["volume_sma"] = ta.sma(df["volume"] if "volume" in df else df["close"] * 100, 20); df["volume"] = df["close"] * 100

    latest, prev = df.iloc[-1], df.iloc[-2]
    price, rsi, macd, macd_signal, sma10, sma50, ema10, ema50, bb_upper, bb_lower, stoch_k = latest[["close", "rsi", "macd", "macd_signal", "sma10", "sma50", "ema10", "ema50", "bb_upper", "bb_lower", "stoch_k"]]
    volume, volume_sma = latest["volume"], latest["volume_sma"]
    last_signal = last_signals.get(coin, {"price": 0, "rsi": 50, "macd": 0, "macd_signal": 0, "sma10": 0, "sma50": 0, "ema10": 0, "ema50": 0, "bb_upper": 0, "bb_lower": 0, "stoch_k": 50})
    last_signals[coin] = latest

    buy_signals, sell_signals = 0, 0
    for curr, prev_val, cond_buy, cond_sell in [(rsi, prev["rsi"], lambda x, y: x < 30 and y >= 30, lambda x, y: x > 70 and y <= 70),
                                               (macd, prev["macd_signal"], lambda x, y: x > y and prev["macd"] <= prev["macd_signal"], lambda x, y: x < y and prev["macd"] >= prev["macd_signal"]),
                                               (price, prev["bb_lower"], lambda x, y: x < y and prev["close"] >= prev["bb_lower"], lambda x, y: x > bb_upper and prev["close"] <= prev["bb_upper"]),
                                               (sma10, prev["sma50"], lambda x, y: x > y and prev["sma10"] <= prev["sma50"], lambda x, y: x < y and prev["sma10"] >= prev["sma50"]),
                                               (ema10, prev["ema50"], lambda x, y: x > y and prev["ema10"] <= prev["ema50"], lambda x, y: x < y and prev["ema50"] >= prev["ema50"]),
                                               (stoch_k, prev["stoch_k"], lambda x, y: x < 20 and y >= 20, lambda x, y: x > 80 and y <= 80)]:
        buy_signals += 1 if cond_buy(curr, prev_val) else 0
        sell_signals += 1 if cond_sell(curr, prev_val) else 0
    if volume > 1.5 * volume_sma: buy_signals += 1 if buy_signals else 0; sell_signals += 1 if sell_signals else 0

    signal = f"BUY {coin.upper()} at ${price:.2f} - {dict(zip(['RSI', 'MACD', 'BB', 'SMA10/50', 'EMA10/50', 'Stoch', 'Vol'], [f'{rsi:.2f}', f'{macd:.2f}/{macd_signal:.2f}', f'{bb_lower:.2f}/{bb_upper:.2f}', f'{sma10:.2f}/{sma50:.2f}', f'{ema10:.2f}/{ema50:.2f}', f'{stoch_k:.2f}', f'{volume:.2f}/{volume_sma:.2f}']))}" if buy_signals >= 3 else \
             f"SELL {coin.upper()} at ${price:.2f} - {dict(zip(['RSI', 'MACD', 'BB', 'SMA10/50', 'EMA10/50', 'Stoch', 'Vol'], [f'{rsi:.2f}', f'{macd:.2f}/{macd_signal:.2f}', f'{bb_lower:.2f}/{bb_upper:.2f}', f'{sma10:.2f}/{sma50:.2f}', f'{ema10:.2f}/{ema50:.2f}', f'{stoch_k:.2f}', f'{volume:.2f}/{volume_sma:.2f}']))}" if sell_signals >= 3 else \
             f"HOLD {coin.upper()} at ${price:.2f} - No signal (Buy: {buy_signals}, Sell: {sell_signals})"
    return signal, (price, rsi, macd, macd_signal, sma10, sma50, ema10, ema50, bb_upper, bb_lower, stoch_k)

def monitor_signals(context):
    chat_id = context.job.context
    if not watchlist: context.bot.send_message(chat_id=chat_id, text="Watchlist empty. Use /add."); return
    for coin in watchlist:
        current_signal, current_values = generate_signal(coin)
        last_signal = last_signals.get(coin, {}).get("signal", "HOLD")
        if current_signal and (current_signal.startswith("BUY") or current_signal.startswith("SELL")) and last_signal.startswith(("HOLD", "SELL", "BUY")[::-1][current_signal.startswith("BUY")]):
            context.bot.send_message(chat_id=chat_id, text=current_signal)
            last_signals[coin] = {"signal": current_signal, **dict(zip(["price", "rsi", "macd", "macd_signal", "sma10", "sma50", "ema10", "ema50", "bb_upper", "bb_lower", "stoch_k"], current_values))}
        time.sleep(1)

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    for cmd in [("start", start), ("add", add), ("remove", remove), ("list", list_coins), ("price", get_price)]: dispatcher.add_handler(CommandHandler(*cmd))
    updater.start_polling()
    job_queue = updater.job_queue
    dispatcher.add_handler(CommandHandler("start", lambda update, context: [start(update, context), job_queue.run_repeating(monitor_signals, 60, 0, context.__setitem__('job', {'context': update.message.chat_id}))[0]]))
    updater.idle()

if __name__ == '__main__':
    main()