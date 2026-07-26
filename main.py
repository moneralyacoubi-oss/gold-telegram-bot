import asyncio
from datetime import datetime

import yfinance as yf
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)


def get_analysis():
    df = yf.download(
        "GC=F",
        period="2d",
        interval="5m",
        progress=False,
        auto_adjust=True,
        multi_level_index=False,
    )

    if df.empty:
        return "❌ لا توجد بيانات حالياً، ربما السوق مغلق."

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]

    macd_obj = MACD(close)
    macd = macd_obj.macd().iloc[-1]
    macd_signal = macd_obj.macd_signal().iloc[-1]

    price = float(close.iloc[-1])

    support = float(low.tail(20).min())
    resistance = float(high.tail(20).max())

    strength = 0

    if ema20 > ema50:
        trend = "🟢 ص
