import asyncio
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

# استبدل هذا الجزء ببياناتك الفعلية
def get_analysis():
    ema20 = 3348.20
    ema50 = 3342.10
    rsi = 58.4
    macd = 1.25
    signal = 0.98

    trend = "📈 الاتجاه العام: صاعد" if ema20 > ema50 else "📉 الاتجاه العام: هابط"

    if rsi > 70:
        rsi_status = "تشبع شرائي"
    elif rsi < 30:
        rsi_status = "تشبع بيعي"
    else:
        rsi_status = "ضمن النطاق الطبيعي"

    if macd > signal:
        macd_status = "MACD أعلى من خط الإشارة"
    else:
        macd_status = "MACD أسفل خط الإشارة"

    return f"""
📊 تحليل الذهب (XAUUSD)

{trend}

EMA20: {ema20}
EMA50: {ema50}

RSI: {rsi:.1f}
الحالة: {rsi_status}

MACD: {macd}
Signal: {signal}
الحالة: {macd_status}

⚠️ هذا تحليل معلوماتي فقط وليس توصية تداول.
"""

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot Started")

    while True:
        msg = get_analysis()
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
