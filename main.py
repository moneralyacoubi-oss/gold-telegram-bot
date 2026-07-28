import asyncio
from datetime import datetime
import requests
import pandas as pd
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID, API_KEY

bot = Bot(token=BOT_TOKEN)

last_signal = None
active_trade = None  # لمتابعة حالة الصفقة الحالية
last_trade_time = datetime.now()  # تتبع وقت آخر صفقة مرسلة

def fetch_data(timeframe, outputsize=100):
    """جلب بيانات السعر من TwelveData"""
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
    """تحليل SMC نقي (BOS / FVG / Ob Levels)"""
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    opens = df["open"]

    # تحديد القمم والقيعان السابقة
    recent_high = highs.tail(15).iloc[:-1].max()
    recent_low = lows.tail(15).iloc[:-1].min()

    last_close = closes.iloc[-1]

    # 1. كسر الهيكل (BOS)
    bos_bullish = last_close > recent_high
    bos_bearish = last_close < recent_low

    # 2. الفجوة السعرية (FVG)
    fvg_bullish = (lows.iloc[-1] > highs.iloc[-3]) and (closes.iloc[-2] > opens.iloc[-2])
    fvg_bearish = (highs.iloc[-1] < lows.iloc[-3]) and (closes.iloc[-2] < opens.iloc[-2])

    # 3. مستويات الستوب الهيكلي
    sl_buy = lows.tail(6).min()
    sl_sell = highs.tail(6).max()

    return {
        "bos_bullish": bos_bullish,
        "bos_bearish": bos_bearish,
        "fvg_bullish": fvg_bullish,
        "fvg_bearish": fvg_bearish,
        "sl_buy": sl_buy,
        "sl_sell": sl_sell
    }

def get_multi_tf_smc():
    """تحديد اتجاه فريم M15 بناءً على SMC"""
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
    global last_signal, active_trade, last_trade_time

    df_m1 = fetch_data("1min", 80)
    df_m5 = fetch_data("5min", 80)

    if df_m1 is None or df_m5 is None:
        return None, None

    close = df_m1["close"]
    price = float(close.iloc[-1])

    # 1. متابعة حالة الصفقة الحالية (TP / SL)
    if active_trade:
        trade_type = active_trade["type"]
        tp1 = active_trade["tp1"]
        tp2 = active_trade["tp2"]
        sl = active_trade["sl"]

        if trade_type == "BUY":
            if price <= sl:
                msg = f"❌ **ضربت إيقاف الخسارة (SL)**\n🪙 GOLD | السعر: `{price:.2f}`"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp2:
                msg = f"🎯🎯 **تم ضرب الهدف الثاني بنجاح (TP2)!**\n🪙 GOLD | السعر: `{price:.2f}`"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                msg = f"🎯 **تحقق الهدف الأول (TP1)!**\n🪙 GOLD | نقل الستوب لنقطة الدخول (`{active_trade['entry']:.2f}`)."
                return "UPDATE", msg

        elif trade_type == "SELL":
            if price >= sl:
                msg = f"❌ **ضربت إيقاف الخسارة (SL)**\n🪙 GOLD | السعر: `{price:.2f}`"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp2:
                msg = f"🎯🎯 **تم ضرب الهدف الثاني بنجاح (TP2)!**\n🪙 GOLD | السعر: `{price:.2f}`"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                msg = f"🎯 **تحقق الهدف الأول (TP1)!**\n🪙 GOLD | نقل الستوب لنقطة الدخول (`{active_trade['entry']:.2f}`)."
                return "UPDATE", msg

        return None, None

    # 2. تحليل SMC الفني الصافي
    smc_m1 = detect_smc_structure(df_m1)
    smc_m5 = detect_smc_structure(df_m5)
    tf_bias = get_multi_tf_smc()

    trade = None
    sl = 0

    # شروط الشراء SMC:
    if smc_m1["bos_bullish"] and (smc_m1["fvg_bullish"] or smc_m5["bos_bullish"]) and tf_bias == "BULLISH":
        trade = "BUY"
        sl = smc_m1["sl_buy"] - 0.50
        risk = price - sl
        if risk <= 0: return None, None
        tp1 = price + (risk * 1.5)
        tp2 = price + (risk * 3.0)

    # شروط البيع SMC:
    elif smc_m1["bos_bearish"] and (smc_m1["fvg_bearish"] or smc_m5["bos_bearish"]) and tf_bias == "BEARISH":
        trade = "SELL"
        sl = smc_m1["sl_sell"] + 0.50
        risk = sl - price
        if risk <= 0: return None, None
        tp1 = price - (risk * 1.5)
        tp2 = price - (risk * 3.0)
    else:
        return None, None

    current_signal = f"{trade}_{round(price, 2)}"
    if current_signal == last_signal:
        return None, None

    last_signal = current_signal
    last_trade_time = datetime.now()

    entry = price
    active_trade = {
        "type": trade,
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "tp1_hit": False
    }

    signal_emoji = "🟢" if trade == "BUY" else "🔴"

    message = f"""{signal_emoji} **{trade}**

📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف الأول:** `{tp1:.2f}`
🎯 **الهدف الثاني:** `{tp2:.2f}`

🛡️ **الستوب:** `{sl:.2f}`
"""
    return "NEW_TRADE", message

async def main():
    global last_trade_time

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="⚡ تم تشغيل البوت بنظام SMC وتنسيق الرسائل الجديد بنجاح!"
        )
    except Exception as e:
        print(f"Telegram Error: {e}")

    last_hourly_report = datetime.now()

    while True:
        try:
            status, msg = check_signal()
            if msg:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )

            now = datetime.now()
            time_since_last_report = (now - last_hourly_report).total_seconds()
            time_since_last_trade = (now - last_trade_time).total_seconds()

            if time_since_last_report >= 3600:
                if time_since_last_trade >= 3600:
                    report_msg = "بعد ما منير حلل السوك طلع ماكو صفقات حالياً 📊"
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=report_msg
                    )
                last_hourly_report = now

        except Exception as e:
            print(f"Loop Error: {e}")

        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
