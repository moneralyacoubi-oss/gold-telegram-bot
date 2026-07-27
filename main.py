import asyncio
import logging
from datetime import datetime

import pandas as pd
import requests

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

from telegram import Bot

from config import BOT_TOKEN, CHAT_ID, API_KEY

# ==========================
# BOT SETTINGS
# ==========================

bot = Bot(token=BOT_TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

SYMBOL = "XAU/USD"

ENTRY_TIMEFRAME = "5min"
CONFIRM_TIMEFRAME = "15min"
TREND_TIMEFRAME = "1h"

OUTPUT_SIZE = 200

MIN_CONFIDENCE = 85

last_signal = None
active_trade = None

BASE_URL = "https://api.twelvedata.com/time_series"


# ==========================
# DOWNLOAD DATA
# ==========================

def get_candles(interval):

    url = (
        f"{BASE_URL}"
        f"?symbol={SYMBOL}"
        f"&interval={interval}"
        f"&outputsize={OUTPUT_SIZE}"
        f"&apikey={API_KEY}"
    )

    data = requests.get(url, timeout=15).json()

    if "values" not in data:
        logging.error(data)
        return None

    df = pd.DataFrame(data["values"])

    df = df.iloc[::-1].reset_index(drop=True)

    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)

    return df
# ==========================
# INDICATORS
# ==========================

def calculate_indicators(df):

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # EMA
    df["ema50"] = EMAIndicator(close, window=50).ema_indicator()
    df["ema200"] = EMAIndicator(close, window=200).ema_indicator()

    # RSI
    df["rsi"] = RSIIndicator(close, window=14).rsi()

    # MACD
    macd = MACD(close)

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    # ATR
    atr = AverageTrueRange(
        high=high,
        low=low,
        close=close,
        window=14
    )

    df["atr"] = atr.average_true_range()

    # ADX
    adx = ADXIndicator(
        high=high,
        low=low,
        close=close,
        window=14
    )

    df["adx"] = adx.adx()

    return df


# ==========================
# SUPPORT & RESISTANCE
# ==========================

def get_support_resistance(df):

    support = df["low"].tail(30).min()

    resistance = df["high"].tail(30).max()

    return support, resistance


# ==========================
# TREND
# ==========================

def get_trend(df):

    last = df.iloc[-1]

    if last["ema50"] > last["ema200"]:
        return "BUY"

    elif last["ema50"] < last["ema200"]:
        return "SELL"

    return "NONE"
# ==========================
# MARKET ANALYSIS
# ==========================

def analyze_market():

    m5 = calculate_indicators(get_candles(ENTRY_TIMEFRAME))
    m15 = calculate_indicators(get_candles(CONFIRM_TIMEFRAME))
    h1 = calculate_indicators(get_candles(TREND_TIMEFRAME))

    if m5 is None or m15 is None or h1 is None:
        return None

    trend_h1 = get_trend(h1)
    trend_m15 = get_trend(m15)
    trend_m5 = get_trend(m5)

    # لازم كل الفريمات بنفس الاتجاه
    if trend_h1 != trend_m15 or trend_h1 != trend_m5:
        return None

    last = m5.iloc[-1]

    confidence = 
# ==========================
# SEND TELEGRAM SIGNAL
# ==========================

async def send_signal(signal):

    global last_signal

    signal_id = f"{signal['signal']}_{round(signal['entry'],2)}"

    if signal_id == last_signal:
        return

    last_signal = signal_id

    message = f"""
🚨 XAU/USD INTRADAY SIGNAL

{'🟢 BUY' if signal['signal']=='BUY' else '🔴 SELL'}

💰 Entry:
{signal['entry']:.2f}

🛑 Stop Loss:
{signal['sl']:.2f}

🎯 TP1:
{signal['tp1']:.2f}

🎯 TP2:
{signal['tp2']:.2f}

🎯 TP3:
{signal['tp3']:.2f}

🔥 Confidence:
{signal['confidence']}%

📊 Strategy:
EMA50 + EMA200
MACD
RSI
ATR
ADX

🕒 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    await bot.send_message(
        chat_id=CHAT_ID,
        text=message
    )
# ==========================
# MAIN LOOP
# ==========================

async def main():

    logging.info("Gold Bot Started...")

    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Gold Intraday Bot Started Successfully"
    )

    while True:

        try:

            signal = analyze_market()

            if signal:
                await send_signal(signal)

        except Exception as e:
            logging.error(e)

        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())
