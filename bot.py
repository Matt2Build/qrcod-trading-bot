from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import requests
import pandas as pd
import pandas_ta as ta
import time

# Initialize watchlist (stored in memory for simplicity)
watchlist = []

# API configuration
API_KEY = "CG-iC6tuTuVhUD72Q9kTQeN62aq"  # Your CoinGecko API key
BASE_URL = "https://api.coingecko.com/api/v3"

# Last known prices and indicators for threshold comparison
last_signals = {}

# Command handler for /start with updated menu
def start(update, context):
    update.message.reply_text("Hello! I'm your day trading bot. I monitor your watchlist and send buy/sell signals when professional trading thresholds are crossed.\n"
                              "Available commands:\n"
                              "/add <coin> - Add a coin to your watchlist (e.g., /add bitcoin)\n"
                              "/remove <coin> - Remove a coin from your watchlist (e.g., /remove bitcoin)\n"
                              "/list - Show your current watchlist\n"
                              "/price <coin> - Get the live price of a coin (e.g., /price btc)")

# Command handler to add a coin to the watchlist
def add(update, context):
    if not context.args:
        update.message.reply_text("Please provide a coin symbol (e.g., /add btc).")
        return
    coin = context.args[0].lower()
    if coin in watchlist:
        update.message.reply_text(f"{coin.upper()} is already in your watchlist.")
    else:
        watchlist.append(coin)
        update.message.reply_text(f"Added {coin.upper()} to your watchlist.")

# Command handler to remove a coin from the watchlist
def remove(update, context):
    if not context.args:
        update.message.reply_text("Please provide a coin symbol (e.g., /remove btc).")
        return
    coin = context.args[0].lower()
    if coin not in watchlist:
        update.message.reply_text(f"{coin.upper()} is not in your watchlist.")
    else:
        watchlist.remove(coin)
        update.message.reply_text(f"Removed {coin.upper()} from your watchlist.")

# Command handler to list the watchlist
def list_coins(update, context):
    if not watchlist:
        update.message.reply_text("Your watchlist is empty. Use /add to add coins.")
    else:
        update.message.reply_text("Your watchlist:\n" + "\n".join([coin.upper() for coin in watchlist]))

# Command handler to fetch live price
def get_price(update, context):
    if not context.args:
        update.message.reply_text("Please provide a coin symbol (e.g., /price btc).")
        return
    coin = context.args[0].lower()
    try:
        url = f"{BASE_URL}/simple/price?ids={coin}&vs_currencies=usd&x_cg_demo_api_key={API_KEY}"
        response = requests.get(url)
        data = response.json()
        if coin not in data or "usd" not in data[coin]:
            update.message.reply_text(f"Could not fetch price for {coin.upper()}. Check the coin ID (e.g., use 'bitcoin' for BTC).")
        else:
            price = data[coin]["usd"]
            update.message.reply_text(f"Live price of {coin.upper()} is ${price:.2f} USD.")
    except Exception as e:
        update.message.reply_text(f"Error fetching price for {coin.upper()}: {str(e)}")

# Fetch historical price data from CoinGecko with API key
def fetch_price_data(coin):
    try:
        url = f"{BASE_URL}/coins/{coin}/ohlc?vs_currency=usd&days=1&interval=5m&x_cg_demo_api_key={API_KEY}"
        response = requests.get(url)
        data = response.json()
        if not data or "status" in data:
            return None
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print(f"Error fetching data for {coin}: {e}")
        return None

# Generate trading signals using professional methods
def generate_signal(coin):
    df = fetch_price_data(coin)
    if df is None or len(df) < 50:  # Need enough data for indicators
        return None, None

    # Calculate technical indicators
    df["rsi"] = ta.rsi(df["close"], length=14)
    macd = ta.macd(df["close"])
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["sma10"] = ta.sma(df["close"], length=10)
    df["sma50"] = ta.sma(df["close"], length=50)
    df["ema10"] = ta.ema(df["close"], length=10)
    df["ema50"] = ta.ema(df["close"], length=50)
    bb = ta.bbands(df["close"], length=20)
    df["bb_upper"] = bb["BBU_20_2.0"]
    df["bb_lower"] = bb["BBL_20_2.0"]
    stoch = ta.stoch(df["high"], df["low"], df["close"])
    df["stoch_k"] = stoch["STOCHk_14_3_3"]
    df["volume_sma"] = ta.sma(df["volume"], length=20) if "volume" in df else ta.sma(df["close"], length=20) * 100  # Approx volume
    df["volume"] = df["close"] * 100  # Placeholder volume

    # Latest data point
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    price = latest["close"]
    rsi = latest["rsi"]
    macd = latest["macd"]
    macd_signal = latest["macd_signal"]
    sma10 = latest["sma10"]
    sma50 = latest["sma50"]
    ema10 = latest["ema10"]
    ema50 = latest["ema50"]
    bb_upper = latest["bb_upper"]
    bb_lower = latest["bb_lower"]
    stoch_k = latest["stoch_k"]
    volume = latest["volume"]
    volume_sma = latest["volume_sma"]

    # Store last signal for threshold comparison
    last_signal = last_signals.get(coin, {"price": 0, "rsi": 50, "macd": 0, "macd_signal": 0, "sma10": 0, "sma50": 0,
                                          "ema10": 0, "ema50": 0, "bb_upper": 0, "bb_lower": 0, "stoch_k": 50})
    last_signals[coin] = latest

    # Professional trading thresholds and conditions
    buy_signals = 0
    sell_signals = 0

    # RSI Thresholds
    if rsi < 30 and prev["rsi"] >= 30:  # Cross below 30 (oversold)
        buy_signals += 1
    elif rsi > 70 and prev["rsi"] <= 70:  # Cross above 70 (overbought)
        sell_signals += 1

    # MACD Thresholds
    if macd > macd_signal and prev["macd"] <= prev["macd_signal"]:  # Bullish crossover
        buy_signals += 1
    elif macd < macd_signal and prev["macd"] >= prev["macd_signal"]:  # Bearish crossover
        sell_signals += 1

    # Bollinger Bands Thresholds
    if price < bb_lower and prev["close"] >= prev["bb_lower"]:  # Cross below lower band
        buy_signals += 1
    elif price > bb_upper and prev["close"] <= prev["bb_upper"]:  # Cross above upper band
        sell_signals += 1

    # SMA Crossover Thresholds
    if sma10 > sma50 and prev["sma10"] <= prev["sma50"]:  # Bullish SMA crossover
        buy_signals += 1
    elif sma10 < sma50 and prev["sma10"] >= prev["sma50"]:  # Bearish SMA crossover
        sell_signals += 1

    # EMA Crossover Thresholds
    if ema10 > ema50 and prev["ema10"] <= prev["ema50"]:  # Bullish EMA crossover
        buy_signals += 1
    elif ema10 < ema50 and prev["ema10"] >= prev["ema50"]:  # Bearish EMA crossover
        sell_signals += 1

    # Stochastic Oscillator Thresholds
    if stoch_k < 20 and prev["stoch_k"] >= 20:  # Cross below 20 (oversold)
        buy_signals += 1
    elif stoch_k > 80 and prev["stoch_k"] <= 80:  # Cross above 80 (overbought)
        sell_signals += 1

    # Volume Confirmation
    if volume > 1.5 * volume_sma:  # Significant volume increase
        buy_signals += 1 if buy_signals > 0 else 0  # Boost buy signal
        sell_signals += 1 if sell_signals > 0 else 0  # Boost sell signal

    # Signal generation based on multiple indicator alignment
    signal = None
    if buy_signals >= 3:  # Require at least 3 buy signals for confirmation
        signal = f"BUY {coin.upper()} at ${price:.2f} - RSI: {rsi:.2f}, MACD: {macd:.2f}/{macd_signal:.2f}, " \
                 f"SMA10: {sma10:.2f}/{sma50:.2f}, EMA10: {ema10:.2f}/{ema50:.2f}, " \
                 f"BB: {bb_lower:.2f}/{bb_upper:.2f}, Stoch: {stoch_k:.2f}, Vol: {volume:.2f}/{volume_sma:.2f}"
    elif sell_signals >= 3:  # Require at least 3 sell signals for confirmation
        signal = f"SELL {coin.upper()} at ${price:.2f} - RSI: {rsi:.2f}, MACD: {macd:.2f}/{macd_signal:.2f}, " \
                 f"SMA10: {sma10:.2f}/{sma50:.2f}, EMA10: {ema10:.2f}/{ema50:.2f}, " \
                 f"BB: {bb_lower:.2f}/{bb_upper:.2f}, Stoch: {stoch_k:.2f}, Vol: {volume:.2f}/{volume_sma:.2f}"
    else:
        signal = f"HOLD {coin.upper()} at ${price:.2f} - No strong signal (Buy: {buy_signals}, Sell: {sell_signals})"

    return signal, (price, rsi, macd, macd_signal, sma10, sma50, ema10, ema50, bb_upper, bb_lower, stoch_k)

# Function to monitor and send signals when thresholds are crossed
def monitor_signals(context):
    chat_id = context.job.context
    if not watchlist:
        context.bot.send_message(chat_id=chat_id, text="Your watchlist is empty. Use /add to add coins.")
        return
    for coin in watchlist:
        current_signal, current_values = generate_signal(coin)
        last_values = last_signals.get(coin, {"price": 0, "rsi": 50, "macd": 0, "macd_signal": 0, "sma10": 0, "sma50": 0,
                                             "ema10": 0, "ema50": 0, "bb_upper": 0, "bb_lower": 0, "stoch_k": 50})
        if current_signal and (current_signal.startswith("BUY") or current_signal.startswith("SELL")):
            last_signal = last_signals.get(coin, {}).get("signal", "HOLD")
            if last_signal.startswith("HOLD") or (current_signal.startswith("BUY") and last_signal.startswith("SELL")) or \
               (current_signal.startswith("SELL") and last_signal.startswith("BUY")):
                context.bot.send_message(chat_id=chat_id, text=current_signal)
                last_signals[coin] = {"signal": current_signal, "price": current_values[0], "rsi": current_values[1],
                                      "macd": current_values[2], "macd_signal": current_values[3], "sma10": current_values[4],
                                      "sma50": current_values[5], "ema10": current_values[6], "ema50": current_values[7],
                                      "bb_upper": current_values[8], "bb_lower": current_values[9], "stoch_k": current_values[10]}
        time.sleep(1)  # Avoid API rate limits

def main():
    # Create the updater with your bot token
    updater = Updater(token='7834300380:AAFgSXjzQSzaugkbwMTl-BnBiZrJRyApRqk', use_context=True)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add))
    dispatcher.add_handler(CommandHandler("remove", remove))
    dispatcher.add_handler(CommandHandler("list", list_coins))
    dispatcher.add_handler(CommandHandler("price", get_price))

    # Start the bot
    updater.start_polling()

    # Run continuous monitoring (e.g., every minute to check thresholds)
    job_queue = updater.job_queue
    def schedule_monitoring(context):
        chat_id = context.job.context
        job_queue.run_repeating(monitor_signals, interval=60, first=0, context=chat_id)

    dispatcher.add_handler(CommandHandler("start", lambda update, context: [start(update, context), schedule_monitoring(context.__setitem__('job', {'context': update.message.chat_id}))]))

    # Keep the bot running until interrupted
    updater.idle()

if __name__ == '__main__':
    main()