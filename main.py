import asyncio
from datetime import datetime
import requests
import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID, API_KEY

bot = Bot(token=BOT_TOKEN)

last_signal = None
active_trade = None  # لمتابعة حالة الصفقة الحالية (TP1, TP2, SL)

def fetch_data(timeframe, outputsize=100):
    """جلب البيانات الفنية لأي إطار زمني"""
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
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching {timeframe}: {e}")
        return None

def get_multi_tf_bias():
    """فلتر الاتجاه العام على M15 و H1"""
    df_m15 = fetch_data("15min", 50)
    df_h1 = fetch_data("1h", 50)

    if df_m15 is None or df_h1 is None:
        return "NEUTRAL"

    ema20_m15 = EMAIndicator(df_m15["close"], window=20).ema_indicator().iloc[-1]
    ema50_m15 = EMAIndicator(df_m15["close"], window=50).ema_indicator().iloc[-1]

    ema20_h1 = EMAIndicator(df_h1["close"], window=20).ema_indicator().iloc[-1]
    ema50_h1 = EMAIndicator(df_h1["close"], window=50).ema_indicator().iloc[-1]

    if ema20_m15 > ema50_m15 and ema20_h1 > ema50_h1:
        return "BULLISH"
    elif ema20_m15 < ema50_m15 and ema20_h1 < ema50_h1:
        return "BEARISH"
    
    return "NEUTRAL"

def check_signal():
    global last_signal, active_trade

    df_m5 = fetch_data("5min", 100)
    if df_m5 is None:
        return None, None

    close = df_m5["close"]
    high = df_m5["high"]
    low = df_m5["low"]

    price = float(close.iloc[-1])

    # 1. متابعة الصفقة الحالية المفتوحة (TP1, TP2, SL)
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
                msg = f"🎯🎯 **تحقق الهدف الثاني بالكامل (TP2)!**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                msg = f"🎯 **تحقق الهدف الأول (TP1)!**\n🪙 GOLD | يُنصح بنقل إيقاف الخسارة لنقطة الدخول ({active_trade['entry']:.2f})."
                return "UPDATE", msg

        elif trade_type == "SELL":
            if price >= sl:
                msg = f"❌ **ضربت إيقاف الخسارة (SL)**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp2:
                msg = f"🎯🎯 **تحقق الهدف الثاني بالكامل (TP2)!**\n🪙 GOLD | السعر: {price:.2f}"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                msg = f"🎯 **تحقق الهدف الأول (TP1)!**\n🪙 GOLD | يُنصح بنقل إيقاف الخسارة لنقطة الدخول ({active_trade['entry']:.2f})."
                return "UPDATE", msg

        return None, None  # لا توجد إشارة جديدة طالما الصفقة مستمرة ولم تحقق هدف أو ستوب

    # 2. حساب المؤشرات للفرص الجديدة (M5)
    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]
    
    macd_obj = MACD(close)
    macd = macd_obj.macd().iloc[-1]
    signal = macd_obj.macd_signal().iloc[-1]

    adx = ADXIndicator(high, low, close, window=14).adx().iloc[-1]
    atr = AverageTrueRange(high, low, close, window=14).average_true_range().iloc[-1]

    # حساب الكسر/الاختراق (Breakout) لأخر 20 شمعة
    recent_high = float(high.tail(20).iloc[:-1].max())
    recent_low = float(low.tail(20).iloc[:-1].min())

    is_breakout_buy = price > recent_high
    is_breakout_sell = price < recent_low

    # الاتجاه من الفريمات الكبيرة
    tf_bias = get_multi_tf_bias()

    # تقييم الإشارة (نظام نقاط صارم V2)
    buy_score = 0
    sell_score = 0

    # شرط قوة الاتجاه (ADX يجب أن يكون > 20 لضمان وجود ترند حقيقي)
    if adx > 20:
        if tf_bias == "BULLISH": buy_score += 30
        if tf_bias == "BEARISH": sell_score += 30

        if ema20 > ema50: buy_score += 20
        else: sell_score += 20

        if macd > signal: buy_score += 20
        else: sell_score += 20

        if rsi > 50 and rsi < 70: buy_score += 15
        elif rsi < 50 and rsi > 30: sell_score += 15

        if is_breakout_buy: buy_score += 15
        if is_breakout_sell: sell_score += 15

    # اتخاذ القرار (يتطلب 85% على الأقل لدخول صفقة عالية الدقة)
    if buy_score >= 85 and tf_bias == "BULLISH":
        trade = "BUY"
        confidence = buy_score
    elif sell_score >= 85 and tf_bias == "BEARISH":
        trade = "SELL"
        confidence = sell_score
    else:
        return None, None

    current_signal = f"{trade}_{round(price, 2)}"
    if current_signal == last_signal:
        return None, None

    last_signal = current_signal

    # حساب الأهداف بناءً على ATR الحقيقي للتأقلم مع تذبذب الذهب
    if trade == "BUY":
        entry = price
        sl = entry - (atr * 1.8)
        tp1 = entry + (atr * 1.5)
        tp2 = entry + (atr * 3.0)
    else:
        entry = price
        sl = entry + (atr * 1.8)
        tp1 = entry - (atr * 1.5)
        tp2 = entry - (atr * 3.0)

    # تسجيل الصفقة الحالية للمتابعة
    active_trade = {
        "type": trade,
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "tp1_hit": False
    }

    signal_emoji = "🟢" if trade == "BUY" else "🔴"

    message = f"""🚀 **إشارة صفقة جديدة (V2 Pro)** 🚀

📌 **القرار:** {signal_emoji} {trade}
🪙 **الأداة:** GOLD (XAU/USD)
🕒 **الاطار الزمني:** M5 (مدعوم بـ M15 & H1)

💵 **سعر الدخول:** {entry:.2f}
🎯 **هدف أول (TP1):** {tp1:.2f}
🎯 **هدف ثاني (TP2):** {tp2:.2f}
🛡️ **إيقاف الخسارة (SL):** {sl:.2f}

📊 **مؤشرات V2 المعززة:**
• **اتجاه (M15 & H1):** {tf_bias} ⚡
• **قوة الاتجاه (ADX):** {adx:.1f} {"(ترند قوي)" if adx > 25 else "(مقبول)"}
• **تذبذب السوق (ATR):** {atr:.2f}
• **اختراق السعر (Breakout):** {"نعم 🔥" if (is_breakout_buy or is_breakout_sell) else "لا"}
🔥 **قوة الإشارة الإجمالية:** {confidence}%

⏰ **الوقت:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    return "NEW_TRADE", message

async def main():
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="🚀 تم تشغيل البوت V2 المطور (ATR + ADX + M15/H1 Filter) بنجاح!"
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

        # التحديث كل دقيقة لمتابعة الأهداف والستوب بسرعة
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
