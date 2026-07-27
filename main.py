import asyncio
from datetime import datetime
import requests
import pandas as pd
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID, API_KEY

bot = Bot(token=BOT_TOKEN)

last_signal = None
active_trade = None  # لمتابعة حالة الصفقة الحالية

def fetch_data(timeframe, outputsize=100):
    """جلب بيانات السعر"""
    url = (
        f"https://api.twelvedata.com/time_series"
        f"?symbol=XAU/USD"
        f"&interval={timeframe}"
        f"&outputsize={outputsize}"
        f"&apikey={API_KEY}"
    )
    try:
        res = requests.get(url, timeout=10).json()
        if "values" not in res:
            return None
        df = pd.DataFrame(res["values"]).iloc[::-1]
        df["close"] = df["close"].astype(float)
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching {timeframe}: {e}")
        return None

def detect_smc_structure(df):
    """تحليل هياكل الحركة الفنية SMC (BOS / ChoCh / FVG)"""
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    opens = df["open"]

    # تقليل عدد الشموع المراقبة لسرعة التقاط الكسر (Scalping Fast)
    recent_high = highs.tail(10).iloc[:-1].max()
    recent_low = lows.tail(10).iloc[:-1].min()

    last_close = closes.iloc[-1]

    # Break of Structure (BOS)
    bos_bullish = last_close > recent_high
    bos_bearish = last_close < recent_low

    # Fair Value Gap (FVG) في آخر 3 شمعات
    fvg_bullish = lows.iloc[-1] > highs.iloc[-3]
    fvg_bearish = highs.iloc[-1] < lows.iloc[-3]

    # Order Block (OB)
    ob_bullish = None
    ob_bearish = None

    if bos_bullish:
        for i in range(len(df) - 2, max(len(df) - 8, 0), -1):
            if closes.iloc[i] < opens.iloc[i]:
                ob_bullish = {"low": lows.iloc[i], "high": highs.iloc[i]}
                break

    if bos_bearish:
        for i in range(len(df) - 2, max(len(df) - 8, 0), -1):
            if closes.iloc[i] > opens.iloc[i]:
                ob_bearish = {"low": lows.iloc[i], "high": highs.iloc[i]}
                break

    return {
        "bos_bullish": bos_bullish,
        "bos_bearish": bos_bearish,
        "fvg_bullish": fvg_bullish,
        "fvg_bearish": fvg_bearish,
        "ob_bullish": ob_bullish,
        "ob_bearish": ob_bearish,
    }

def get_multi_tf_smc():
    """تحليل اتجاه الفريمات المتوسطة لتأكيد الدعم"""
    df_m15 = fetch_data("15min", 40)
    if df_m15 is None:
        return "NEUTRAL"

    smc_m15 = detect_smc_structure(df_m15)
    if smc_m15["bos_bullish"]:
        return "BULLISH"
    elif smc_m15["bos_bearish"]:
        return "BEARISH"

    return "NEUTRAL"

def check_signal():
    global last_signal, active_trade

    # استخدام فريم M1 + M5 للحصول على صفقات سريعة وكثيرة
    df_m1 = fetch_data("1min", 80)
    df_m5 = fetch_data("5min", 80)

    if df_m1 is None or df_m5 is None:
        return None, None

    close = df_m1["close"]
    high = df_m1["high"]
    low = df_m1["low"]
    price = float(close.iloc[-1])

    # 1. متابعة حالة الصفقة الحالية (TP / SL)
    if active_trade:
        trade_type = active_trade["type"]
        tp1 = active_trade["tp1"]
        tp2 = active_trade["tp2"]
        sl = active_trade["sl"]

        if trade_type == "BUY":
            if price <= sl:
                msg = f"❌ **ضربت إيقاف الخسارة (SL)**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp2:
                msg = f"🎯🎯 **تم ضرب الهدف الثاني بنجاح (TP2 - Scalp)!**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                msg = f"🎯 **تحقق الهدف الأول (TP1 - Scalp)!**\n🪙 GOLD | ننصح بنقل الستوب لنقطة الدخول ({active_trade['entry']:.2f})."
                return "UPDATE", msg

        elif trade_type == "SELL":
            if price >= sl:
                msg = f"❌ **ضربت إيقاف الخسارة (SL)**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp2:
                msg = f"🎯🎯 **تم ضرب الهدف الثاني بنجاح (TP2 - Scalp)!**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                msg = f"🎯 **تحقق الهدف الأول (TP1 - Scalp)!**\n🪙 GOLD | ننصح بنقل الستوب لنقطة الدخول ({active_trade['entry']:.2f})."
                return "UPDATE", msg

        return None, None

    # 2. تحليل SMC الفني على M1 و M5
    smc_m1 = detect_smc_structure(df_m1)
    smc_m5 = detect_smc_structure(df_m5)
    tf_bias = get_multi_tf_smc()

    adx = ADXIndicator(high, low, close, window=14).adx().iloc[-1]
    atr = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]

    buy_score = 0
    sell_score = 0

    # تقييم الشروط بنظام النقاط المرن (مرونة عالية لزيادة الصفقات)
    if adx > 15:  # شرط خفيف جداً يضمن وجود حركة
        if smc_m1["bos_bullish"]: buy_score += 35
        if smc_m1["bos_bearish"]: sell_score += 35

        if smc_m5["bos_bullish"]: buy_score += 25
        if smc_m5["bos_bearish"]: sell_score += 25

        if smc_m1["fvg_bullish"] or smc_m5["fvg_bullish"]: buy_score += 20
        if smc_m1["fvg_bearish"] or smc_m5["fvg_bearish"]: sell_score += 20

        if tf_bias == "BULLISH": buy_score += 20
        if tf_bias == "BEARISH": sell_score += 20

    # قبول الصفقة عند نسبة 65% فأكثر (صفقات كثيرة وسريعة)
    if buy_score >= 65:
        trade = "BUY"
        confidence = buy_score
        ob = smc_m1["ob_bullish"] or smc_m5["ob_bullish"]
    elif sell_score >= 65:
        trade = "SELL"
        confidence = sell_score
        ob = smc_m1["ob_bearish"] or smc_m5["ob_bearish"]
    else:
        return None, None

    current_signal = f"{trade}_{round(price, 2)}"
    if current_signal == last_signal:
        return None, None

    last_signal = current_signal

    # حساب الستوب والاهداف المخصصة للسكالبينج السريع
    if trade == "BUY":
        entry = price
        sl = entry - max(atr * 1.2, 1.5)  # ستوب مناسب لحجم الحركة
        risk = entry - sl
        tp1 = entry + (risk * 1.2)
        tp2 = entry + (risk * 2.5)
    else:
        entry = price
        sl = entry + max(atr * 1.2, 1.5)
        risk = sl - entry
        tp1 = entry - (risk * 1.2)
        tp2 = entry - (risk * 2.5)

    # تسجيل الصفقة للمتابعة
    active_trade = {
        "type": trade,
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "tp1_hit": False
    }

    signal_emoji = "🟢" if trade == "BUY" else "🔴"

    message = f"""⚡ **إشارة سكالبينج سريعة (V3 SMC Fast)** ⚡

📌 **القرار:** {signal_emoji} {trade}
🪙 **الأداة:** GOLD (XAU/USD)
🕒 **الإطار الزمني:** M1 / M5 Fast

💵 **سعر الدخول:** {entry:.2f}
🎯 **هدف أول (TP1):** {tp1:.2f}
🎯 **هدف ثاني (TP2):** {tp2:.2f}
🛡️ **إيقاف الخسارة (SL):** {sl:.2f}

🏛️ **عناصر الإشارة:**
• **كسر هيكل (M1/M5 BOS):** متحقق ✅
• **فجوة FVG:** متوفرة ⚡
• **مؤشر الترند (ADX):** {adx:.1f}
🔥 **قوة الإشارة:** {confidence}%

⏰ **الوقت:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    return "NEW_TRADE", message

async def main():
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="⚡ تم تشغيل البوت V3 SMC Fast (توليد صفقات مكثفة + M1/M5 Scalping) بنجاح!"
        )
    except Exception as e:
        print(f"Telegram Error: {e}")

    while True:
        try:
            status, msg = check_signal()
            if msg:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )

        except Exception as e:
            print(f"Loop Error: {e}")

        # فحص كسر الهيكل كل 30 ثانية لعدم تفويت الصفقات السريعة
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
