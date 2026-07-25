import asyncio
import requests
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.trend import MACD
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(BOT_TOKEN)

API_KEY = "ضع_مفتاح_API_هنا"

def get_analysis():
    url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=5min&outputsize=100&apikey={API_KEY}"
    data = requests.get(url).json()

    df = pd.DataFrame(data["values"])
    df["close"] = df["close"].astype(float)
    df = df.iloc[::-1]

    ema20 = EMAIndicator(df["close"], window=20).ema_indicator().
