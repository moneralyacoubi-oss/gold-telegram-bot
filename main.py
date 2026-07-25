import asyncio
import requests
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.trend import MACD
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(BOT_TOKEN)

API_KEY = "pub_fb92c046adc2458f8f3cdf25d2f37c4b"

def get_analysis():
    url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=5min&outputsize=100&apikey={API_KEY}"
    data = requests.get(url).json()

    df = pd.DataFrame(data["values"])
    df["close"] = df["close"].astype(float)
    df = df.iloc[::-1]

    ema20 = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(df["close"], window=14).rsi().iloc[-1]
    macd = MACD(df["close"]).macd().iloc[-1]
    signal = MACD(df["close"]).macd_signal().iloc[-1]
    price = df["close"].iloc[-1]

    return f"""
📊 Gold Analysis

💰 Price: {price:.2f}
📈 EMA20: {ema20:.2f}
📉 EMA50: {ema50:.2f}
📊 RSI: {rsi:.2f}
📉 MACD: {macd:.3f}
📈 Signal: {signal:.3f}

⚠️ معلومات تحليلية فقط وليست توصية تداول.
"""

async def main():
    await bot.send_message(CHAT_ID, "✅ Gold Analysis Bot Started")

    while True:
        try:
            analysis = get_analysis()
            await bot.send_message(CHAT_ID, analysis)
        except Exception as e:
            await bot.send_message(CHAT_ID, f"❌ Error: {e}")

        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
