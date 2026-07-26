import asyncio
from datetime import datetime

import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)


def get_analysis():
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=100"

        response = requests.get(url, timeout=10)
        res = response.json()

        # إظهار الخطأ الحقيقي إذا فشل الطلب
        if not isinstance(res, list):
            return f"❌ Binance Error:\n{res}"

        if len(res) == 0:
            return "❌ لم يتم استلام أي بيانات من Binance."

        df = pd.DataFrame(
            res,
            columns=[
                "open_time",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "close_time",
                "q_vol",
                "num_trades",
                "taker_base",
                "taker_quote",
                "ignore",
            ],
        )

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
       
