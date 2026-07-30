import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)
4ae67ca80f844c3ba85c3fae51daa8c5
API_KEY = "YOUR_TWELVEDATA_API_KEY_HERE".strip()

# ضبط التوقيت المحلي على بغداد (UTC+3)
IRAQ_TZ = pytz.timezone("Asia/Baghdad")

def get_now():
    return datetime.now(IRAQ_TZ)

last_signal = None
active_trade = None
last_trade_time = get_now()
last_trade_closed_time = get_now()

daily_stats = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_pips": 0.0,
    "last_reset_date": get_now().date()
}

def is_news_time():
    try:
        url = "https://nws.forexfactory1.com/forex_calendar.json"
        res = requests.get(url, timeout=4).json()
        now = get_now().replace(tzinfo=None)
        
        for event in res:
            if event.get("country") == "USD" and event.get("impact") == "High":
                event_time_str = f"{event.get('date')} {event.get('time')}"
                event_dt = datetime.strptime(event_time_str, "%Y-%m-%d %I:%M%p")
                
                diff_minutes = abs((now - event_dt).total_seconds()) / 60.0
                if diff_minutes <= 15:
                    return True, event.get("title")
    except Exception:
        pass
    return False, None

def reset_daily_stats_if_needed():
    global daily_stats
    today = get_now().date()
    if daily_stats["last_reset_date"] != today:
        daily_stats = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pips": 0.0,
            "last_reset_date": today
        }

def fetch_data(timeframe, outputsize=100):
    url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={timeframe}&outputsize={outputsize}&apikey={API_KEY}"
    try:
        res = requests.get(url, timeout=8).json()
        if "values" not in res:
            print(f"⚠️ API Response Error ({timeframe}): {res}")
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

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def detect_smart_signals(df_m5, df_h1):
    # 1. تحليل الاتجاه الحاكم على فريم الساعة 1H
    h1_closes = df_h1["close"]
    h1_ema200 = h1_closes.ewm(span=200, adjust=False).mean().iloc[-1]
    h1_last_close = h1_closes.iloc[-1]
    
    h1_is_uptrend = h1_last_close > h1_ema200
    h1_is_downtrend = h1_last_close < h1_ema200

    # 2. تحليل الدخول على فريم الـ 5 دقائق M5
    m5_closes = df_m5["close"]
    m5_highs = df_m5["high"]
    m5_lows = df_m5["low"]

    m5_last_close = m5_closes.iloc[-1]
    m5_ema200 = m5_closes.ewm(span=200, adjust=False).mean().iloc[-1]
    rsi = calculate_rsi(m5_closes, 14).iloc[-1]

    recent_high = m5_highs.tail(6).iloc[:-1].max()
    recent_low = m5_lows.tail(6).iloc[:-1].min()

    # يجب أن يتوافق فريم 5 دقائق مع اتجاه فريم الساعة 1H
    bos_bullish = (m5_last_close > recent_high) and (m5_last_close > m5_ema200) and h1_is_uptrend and (rsi < 68)
    bos_bearish = (m5_last_close < recent_low) and (m5_last_close < m5_ema200) and h1_is_downtrend and (rsi > 32)

    sl_buy = m5_lows.tail(3).min() - 0.20
    sl_sell = m5_highs.tail(3).max() + 0.20

    return {
        "bos_bullish": bos_bullish,
        "bos_bearish": bos_bearish,
        "sl_buy": sl_buy,
        "sl_sell": sl_sell
    }

def check_signal():
    global last_signal, active_trade, last_trade_time, daily_stats, last_trade_closed_time

    reset_daily_stats_if_needed()

    df_m5 = fetch_data("5min", 100)
    df_h1 = fetch_data("1h", 210) # يجلب 210 شمعة لحساب EMA 200 للساعة

    if df_m5 is None or df_h1 is None or len(df_m5) < 50 or len(df_h1) < 200:
        return None, None

    close = df_m5["close"]
    price = float(close.iloc[-1])
    now = get_now()
    
    print(f"🔍 [تحليل حي MTF] السعر: {price:.2f} | الوقت: {now.strftime('%H:%M:%S')}")

    # متابعة الصفقة الحالية إذا كانت مفتوحة
    if active_trade:
        trade_type = active_trade["type"]
        entry = active_trade["entry"]
        tp1 = active_trade["tp1"]
        sl = active_trade["sl"]
        is_be_moved = active_trade.get("be_moved", False)
        entry_time = active_trade.get("entry_time", now)

        # ------------------ الفكرة الثانية: نقل الستوب التلقائي لحماية الأرباح (Breakeven) ------------------
        if trade_type == "BUY":
            current_gain_pips = (price - entry) * 10
            # نقل الستوب لنقطة الدخول إذا تحقق +15 نقطة ولم ينقل سابقاً
            if current_gain_pips >= 15.0 and not is_be_moved:
                active_trade["sl"] = entry # تعديل الستوب ليصبح سعر الدخول نفسه
                active_trade["be_moved"] = True
                msg = (
                    f"🛡️ **تأمين الصفقة (Breakeven)!**\n"
                    f"الصفقة: **BUY** | السعر: `{price:.2f}`\n"
                    f"💡 **حققت الصفقة +15 نقطة:** تم نقل الستوب تلقائياً إلى نقطة الدخول (`{entry:.2f}`). الصفقة الآن بدون أي مخاطرة! 🚀"
                )
                return "UPDATE", msg

            # ضرب الستوب (أو الدخول بعد التأمين)
            if price <= active_trade["sl"]:
                pips_result = round((active_trade["sl"] - entry) * 10, 1)
                if pips_result >= 0:
                    daily_stats["wins"] += 1
                    daily_stats["total_pips"] += pips_result
                    msg = f"⚖️ **إغلاق على نقطة الدخول (Breakeven)**\n🪙 GOLD | السعر: `{price:.2f}`\nالنتيجة: أرباح محمية / بدون خسارة."
                else:
                    daily_stats["losses"] += 1
                    daily_stats["total_pips"] += pips_result
                    msg = f"❌ **ضربت الستوب (SL)**\n🪙 GOLD | السعر: `{price:.2f}`\n📉 الخسارة: `{pips_result}` Pip"
                
                active_trade = None
                last_trade_closed_time = now
                return "UPDATE", msg

            elif price >= tp1:
                pips_gained = round((tp1 - entry) * 10, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = (
                    f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n"
                    f"💰 **توصية:** إغلاق 50% ونقل الستوب لنقطة الدخول (`{entry:.2f}`).\n"
                    f"⚡ البوت متاح الآن لفرص جديدة."
                )
                active_trade = None
                last_trade_closed_time = now
                return "UPDATE", msg

        elif trade_type == "SELL":
            current_gain_pips = (entry - price) * 10
            # نقل الستوب لنقطة الدخول إذا تحقق +15 نقطة ولم ينقل سابقاً
            if current_gain_pips >= 15.0 and not is_be_moved:
                active_trade["sl"] = entry
                active_trade["be_moved"] = True
                msg = (
                    f"🛡️ **تأمين الصفقة (Breakeven)!**\n"
                    f"الصفقة: **SELL** | السعر: `{price:.2f}`\n"
                    f"💡 **حققت الصفقة +15 نقطة:** تم نقل الستوب تلقائياً إلى نقطة الدخول (`{entry:.2f}`). الصفقة الآن بدون أي مخاطرة! 🚀"
                )
                return "UPDATE", msg

            if price >= active_trade["sl"]:
                pips_result = round((entry - active_trade["sl"]) * 10, 1)
                if pips_result >= 0:
                    daily_stats["wins"] += 1
                    daily_stats["total_pips"] += pips_result
                    msg = f"⚖️ **إغلاق على نقطة الدخول (Breakeven)**\n🪙 GOLD | السعر: `{price:.2f}`\nالنتيجة: أرباح محمية / بدون خسارة."
                else:
                    daily_stats["losses"] += 1
                    daily_stats["total_pips"] += pips_result
                    msg = f"❌ **ضربت الستوب (SL)**\n🪙 GOLD | السعر: `{price:.2f}`\n📉 الخسارة: `{pips_result}` Pip"

                active_trade = None
                last_trade_closed_time = now
                return "UPDATE", msg

            elif price <= tp1:
                pips_gained = round((entry - tp1) * 10, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = (
                    f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n"
                    f"💰 **توصية:** إغلاق 50% ونقل الستوب لنقطة الدخول (`{entry:.2f}`).\n"
                    f"⚡ البوت متاح الآن لفرص جديدة."
                )
                active_trade = None
                last_trade_closed_time = now
                return "UPDATE", msg

        # شرط مرور ساعتين (120 دقيقة)
        time_elapsed = (now - entry_time).total_seconds() / 60.0
        if time_elapsed >= 120:
            if trade_type == "BUY":
                diff_pips = round((price - entry) * 10, 1)
            else:
                diff_pips = round((entry - price) * 10, 1)

            if diff_pips > 0:
                advice = f"اخرجوا منها الآن **بربح (+{diff_pips} Pip) 🟢**"
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += diff_pips
            elif diff_pips < 0:
                advice = f"اخرجوا منها الآن **بخسارة ({diff_pips} Pip) 🔴**، بعدين نعوضها إن شاء الله 🚀"
                daily_stats["losses"] += 1
                daily_stats["total_pips"] += diff_pips
            else:
                advice = "اخرجوا منها الآن **على نقطة الدخول ⚖️**"

            msg = (
                f"⏳ **تحديث الصفقة (مرور ساعتين)**\n\n"
                f"الصفقة: **{trade_type}**\n"
                f"📍 سعر الدخول: `{entry:.2f}`\n"
                f"📊 السعر الحالي: `{price:.2f}`\n\n"
                f"💡 **توصية منير:** {advice}\n"
                f"⚡ البوت متفرغ الآن لفرص جديدة."
            )
            active_trade = None
            last_trade_closed_time = now
            return "UPDATE", msg

        return None, None

    cooldown_minutes = (now - last_trade_closed_time).total_seconds() / 60.0
    if cooldown_minutes < 15:
        return None, None

    has_news, news_title = is_news_time()
    if has_news:
        print(f"🛑 تجنب الدخول بسبب الأخبار: {news_title}")
        return None, None

    # ------------------ الفكرة الأولى: البحث عن إشارات متوافقة مع فريم الساعة 1H ------------------
    signals = detect_smart_signals(df_m5, df_h1)

    trade = None
    sl = 0

    if signals["bos_bullish"]:
        trade = "BUY"
        calculated_sl = signals["sl_buy"]
        sl = max(calculated_sl, price - 3.50)
        risk = price - sl
        if risk <= 0.5: return None, None
        tp1 = price + (risk * 1.5)
        tp2 = price + (risk * 3.0)

    elif signals["bos_bearish"]:
        trade = "SELL"
        calculated_sl = signals["sl_sell"]
        sl = min(calculated_sl, price + 3.50)
        risk = sl - price
        if risk <= 0.5: return None, None
        tp1 = price - (risk * 1.5)
        tp2 = price - (risk * 3.0)
    else:
        return None, None

    current_signal = f"{trade}_{round(price, 2)}"
    if current_signal == last_signal:
        return None, None

    last_signal = current_signal
    last_trade_time = now

    entry = price
    active_trade = {
        "type": trade,
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "be_moved": False,
        "entry_time": now
    }

    daily_stats["total_trades"] += 1
    signal_emoji = "🟢" if trade == "BUY" else "🔴"

    message = f"""{signal_emoji} **{trade}** (إشارة مؤسساتية 🏛️ Multi-Timeframe)

📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف الأول:** `{tp1:.2f}`
🎯 **الهدف الثاني:** `{tp2:.2f}`

🛡️ **الستوب المحمي:** `{sl:.2f}`
⏳ **نظام التأمين:** ينقل الستوب تلقائياً إلى الدخول عند +15 نقطة.

📈 [عرض الشارت الحي على TradingView](https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD)
"""
    return "NEW_TRADE", message

async def send_daily_summary():
    pips = daily_stats["total_pips"]
    pips_str = f"+{pips:.1f}" if pips >= 0 else f"{pips:.1f}"
    
    summary_msg = f"""📊 **التقرير اليومي لأداء البوت** 📊

🔢 **إجمالي الصفقات:** `{daily_stats['total_trades']}`
✅ **الربحة:** `{daily_stats['wins']}`
❌ **الخاسرة:** `{daily_stats['losses']}`
📈 **صافي النقاط:** `{pips_str}` Pips

منير يحييكم وينتظركم غداً مع صفقات جديدة! 🚀
"""
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=summary_msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Summary Error: {e}")

async def main():
    global last_trade_time

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="🚀 **تم إطلاق الإصدار V3 الفائق!**\n\n🔹 تفعيل فلتر الاتجاه الحاكم (فريم الساعة 1H)\n🔹 تفعيل نظام التأمين التلقائي للستوب (Breakeven عند +15 نقطة)"
        )
    except Exception as e:
        print(f"Telegram Error: {e}")

    last_hourly_report = get_now()
    daily_summary_sent_today = False

    while True:
        try:
            status, msg = check_signal()
            if msg:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown",
                    disable_web_page_preview=False
                )

            now = get_now()
            time_since_last_report = (now - last_hourly_report).total_seconds()
            time_since_last_trade = (now - last_trade_time).total_seconds()

            if now.hour == 23 and now.minute >= 55 and not daily_summary_sent_today:
                await send_daily_summary()
                daily_summary_sent_today = True

            if now.hour == 0 and now.minute < 5:
                daily_summary_sent_today = False

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

        await asyncio.sleep(110)

if __name__ == "__main__":
    asyncio.run(main())
