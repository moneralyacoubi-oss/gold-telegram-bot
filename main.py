import asyncio
import yfinance as yf
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

def get_analysis():
    df = yf.download("GC=F", period="2d", interval="5m", progress=False)

    if df.empty:
        return "❌ فشل في جلب البيانات"

    close = df["Close"].squeeze()

    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(close).rsi().iloc[-1]

    macd = MACD(close)
    macd_value = macd.macd().iloc[-1]
    signal_value = macd.macd_signal().iloc[-1]

    price = float(close.iloc[-1])

    if ema20 > ema50 and macd_value > signal_value and rsi < 70:
        rec = "🟢 BUY"
    elif ema20 < ema50 and macd_value < signal_value and rsi > 30:
        rec = "🔴 SELL"
    else:
        rec = "🟡 WAIT"

    return f"""
📊 Gold Analysis

💰 Price: {price:.2f}
📈 EMA20: {ema20:.2f}
📉 EMA50: {ema50:.2f}
📊 RSI: {rsi:.2f}
📈 MACD: {macd_value:.2f}

🔥 Signal: {rec}
"""

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot Started")

    while True:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=get_analysis())
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"❌ {e}")

        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
