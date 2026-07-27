import asyncio
from datetime import datetime
import requests
import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID, API_KEY

bot = Bot(token=BOT_TOKEN)

last_signal = None


def get_analysis():
    global last_signal

    try:
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol=XAU/USD"
            f"&interval=5min"
            f"&outputsize=100"
            f"&apikey={API_KEY}"
        )

        data = requests.get(url, timeout=10).json()

        if "values" not in data:
            return None

        df = pd.DataFrame(data["values"])
        df = df.iloc[::-1]

        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # المؤشرات الفنية
        ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
        ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
        rsi = RSIIndicator(close, window=14).rsi().iloc[-1]

        macd_obj = MACD(close)
        macd = macd_obj.macd().iloc[-1]
        signal = macd_obj.macd_signal().iloc[-1]

        price = float(close.iloc[-1])

        # حساب الدعوم والمقاومات
        support = float(low.tail(20).min())
        resistance = float(high.tail(20).max())

        buy_score = 0
        sell_score = 0

        # الاستراتيجيات المتعددة (EMA + MACD + RSI)
        if ema20 > ema50:
            buy_score += 40
        else:
            sell_score += 40

        if macd > signal:
            buy_score += 35
        else:
            sell_score += 35

        if rsi < 35:
            buy_score += 25
        elif rsi > 65:
            sell_score += 25
        else:
            buy_score += 10
            sell_score += 10

        # اتخاذ القرار بفتح صفقة
        if buy_score >= 80:
            trade = "BUY"
            signal_emoji = "🟢"
            confidence = buy_score
        elif sell_score >= 80:
            trade = "SELL"
            signal_emoji = "🔴"
            confidence = sell_score
        else:
            return None

        # منع تكرار نفس الإشارة
        current_signal = f"{trade}_{round(price, 2)}"

        if current_signal == last_signal:
            return None

        last_signal = current_signal

        # حساب مستويات الصفقة (إيقاف الخسارة وجني الأرباح)
        if trade == "BUY":
            entry = price
            stop_loss = support

            risk = entry - stop_loss
            if risk <= 0:
                risk = price * 0.002

            tp1 = entry + risk
            tp2 = entry + (risk * 2)

        else:  # SELL
            entry = price
            stop_loss = resistance

            risk = stop_loss - entry
            if risk <= 0:
                risk = price * 0.002

            tp1 = entry - risk
            tp2 = entry - (risk * 2)

        # نصوص حالة المؤشرات للعرض في الصفقة
        macd_status = "إيجابي 🟢" if macd > signal else "سلبي 🔴"
        ema_status = "صاعد (EMA20 > EMA50) 🟢" if ema20 > ema50 else "هابط (EMA20 < EMA50) 🔴"

        # قالب الرسالة المنسق لصفقة التداول المنظمة
        return f"""🚨 **تنبيه صفقة تداول جديدة** 🚨

📌 **القرار:** {signal_emoji} {trade}
🪙 **الأداة:** GOLD (XAU/USD)
🕒 **الاطار الزمني:** M5

💵 **سعر الدخول:** {entry:.2f}
🎯 **هدف أول (TP1):** {tp1:.2f}
🎯 **هدف ثاني (TP2):** {tp2:.2f}
🛡️ **إيقاف الخسارة (SL):** {stop_loss:.2f}

📊 **دوافع الصفقة (الاستراتيجية):**
• **اتجاه المتوسطات:** {ema_status}
• **RSI:** {rsi:.2f}
• **MACD:** {macd_status}
🔥 **قوة الإشارة:** {confidence}%

⏰ **الوقت:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    except Exception as e:
        print(f"Analysis Error: {e}")
        return None


async def main():
    # رسالة بدء التشغيل
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="✅ تم تشغيل بوت صفقات الذهب بنجاح!"
        )
    except Exception as e:
        print(f"Telegram Startup Error: {e}")

    while True:
        try:
            analysis = get_analysis()

            # يرسل فقط إذا توجد صفقة قوية ومطابقة للشروط
            if analysis:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=analysis,
                    parse_mode="Markdown"
                )

        except Exception as e:
            print(f"Execution Error: {e}")

        # فحص وتحديث كل 5 دقائق
        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())
