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
⚠️ هذا تحليل منير  وليس توصية استثمارية.
"""


async def main():
    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Gold Analysis Bot Started"
    )

    while True:
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=get_analysis()
            )
        except Exception as e:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"❌ Error:\n{e}"
            )

        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())
