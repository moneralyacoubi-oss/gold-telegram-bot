import asyncio
import yfinance as yf
import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

df = yf.download(
    "GC=F",
    period="2d",
    interval="5m",
    progress=False,
    auto_adjust=True,
    multi_level_index=False
)

    if df.empty:
        return "❌ فشل في جلب بيانات الذهب."

 
close = df["Close"]

if isinstance(close, pd.DataFrame):
    close = close.iloc[:, 0]

close = pd.Series(close).astype(float)).astype(float)
    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]

    macd = MACD(close)
    macd_value = macd.macd().iloc[-1]
    signal_value = macd.macd_signal().iloc[-1]

    price = close.iloc[-1]

    if ema20 > ema50 and rsi < 70 and macd_value > signal_value:
        signal = "🟢 BUY"
    elif ema20 < ema50 and rsi > 30 and macd_value < signal_value:
        signal = "🔴 SELL"
    else:
        signal = "🟡 WAIT"

    return f"""
📊 Gold Analysis

💰 Price: {price:.2f}

📈 EMA20: {ema20:.2f}
📉 EMA50: {ema50:.2f}

📊 RSI: {rsi:.2f}

📈 MACD: {macd_value:.2f}
📉 Signal: {signal_value:.2f}

🔥 Recommendation:
{signal}

⚠️ للتحليل فقط وليس توصية استثمارية.
"""

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="✅ Gold Analysis Bot Started")

    while True:
        try:
            msg = get_analysis()
            await bot.send_message(chat_id=CHAT_ID, text=msg)
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"❌ Error:\n{e}")

        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
