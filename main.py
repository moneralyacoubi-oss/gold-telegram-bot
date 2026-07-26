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
        # جلب بيانات الشموع اللحظية للذهب الفوري (فريم 5 دقائق) المطابق لـ MT5
        url = "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=100"
        res = requests.get(url, timeout=10).json()

        if not isinstance(res, list) or len(res) == 0:
            return "❌ لا توجد بيانات حالياً، ربما السوق مغلق."

        # تحويل البيانات إلى DataFrame
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
        low = df["Low"].astype(float)

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
            trend = "🟢 صاعد"
            strength += 40
        else:
            trend = "🔴 هابط"

        if macd > macd_signal:
            macd_text = "🟢 إيجابي"
            strength += 30
        else:
            macd_text = "🔴 سلبي"

        if rsi < 30:
            rsi_text = "🟢 تشبع بيعي"
            strength += 30
        elif rsi > 70:
            rsi_text = "🔴 تشبع شرائي"
        else:
            rsi_text = "🟡 طبيعي"
            strength += 15

        if strength >= 70:
            signal = "🟢 BUY"
        elif strength <= 30:
            signal = "🔴 SELL"
        else:
            signal = "🟡 WAIT"

        return f"""📊 GOLD ANALYSIS
━━━━━━━━━━━━━━━━━━

💰 السعر:
{price:.2f}

📈 الاتجاه:
{trend}

📊 RSI:
{rsi:.2f} - {rsi_text}

📉 MACD:
{macd_text}

🟢 الدعم:
{support:.2f}

🔴 المقاومة:
{resistance:.2f}

🎯 قوة الإشارة:
{strength}%

📌 القرار:
{signal}

🕒 الفريم:
5 Minutes

⏰ وقت التحليل:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

━━━━━━━━━━━━━━━━━━
⚠️ هذا تحليل منير وليس توصية استثمارية.
"""
    except Exception as e:
        return f"❌ حدث خطأ أثناء إعداد التحليل:\n{e}"


async def main():
    await bot.send_message(
        chat_id=CHAT_ID, text="✅ Gold Analysis Bot Started"
    )

    while True:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=get_analysis())
        except Exception as e:
            await bot.send_message(chat_id=CHAT_ID, text=f"❌ Error:\n{e}")

        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())
