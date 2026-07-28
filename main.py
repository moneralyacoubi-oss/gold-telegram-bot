import asyncio
from datetime import datetime, time
import requests
import pandas as pd
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID, API_KEY

bot = Bot(token=BOT_TOKEN)

last_signal = None
active_trade = None  # لمتابعة حالة الصفقة الحالية
last_trade_time = datetime.now()  # تتبع وقت آخر صفقة مرسلة

# متغيرات التقرير اليومي
daily_stats = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_pips": 0.0,
    "last_reset_date": datetime.now().date()
}

def is_news_time():
    """
    التحقق من وجود أخبار عالية التأثير على الدولار الأمريكي (High Impact USD News)
    يتم تجميد التداول قبل وبعد الخبر بـ 15 دقيقة
    """
    try:
        url = "https://nws.forexfactory1.com/forex_calendar.json" # مصدر خفيف وجاهز للأخبار
        res = requests.get(url, timeout=5).json()
        now = datetime.now()
        
        for event in res:
            if event.get("country") == "USD" and event.get("impact") == "High":
                # تحويل وقت الخبر إلى datetime
                event_time_str = f"{event.get('date')} {event.get('time')}"
                event_dt = datetime.strptime(event_time_str, "%Y-%m-%d %I:%M%p")
                
                # حساب الفارق بالدقائق
                diff_minutes = abs((now - event_dt).total_seconds()) / 60.0
                if diff_minutes <= 15:
                    return True, event.get("title")
    except Exception:
        # في حال حدوث خطأ في شبكة الأخبار، يكمل البوت عمله الطبيعي
        pass
    return False, None

def reset_daily_stats_if_needed():
    """إعادة إحصائيات اليوم عند تغيير التاريخ"""
    global daily_stats
    today = datetime.now().date()
    if daily_stats["last_reset_date"] != today:
        daily_stats = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pips": 0.0,
            "last_reset_date": today
        }

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
    global last_signal, active_trade, last_trade_time, daily_stats

    reset_daily_stats_if_needed()

    df_m1 = fetch_data("1min", 80)
    df_m5 = fetch_data("5min", 80)

    if df_m1 is None or df_m5 is None:
        return None, None

    close = df_m1["close"]
    price = float(close.iloc[-1])

    # 1. متابعة حالة الصفقة الحالية (TP / SL)
    if active_trade:
        trade_type = active_trade["type"]
        entry = active_trade["entry"]
        tp1 = active_trade["tp1"]
        tp2 = active_trade["tp2"]
        sl = active_trade["sl"]

        if trade_type == "BUY":
            if price <= sl:
                pips_lost = round((sl - entry) * 10, 1)
                daily_stats["losses"] += 1
                daily_stats["total_pips"] += pips_lost
                msg = f"❌ **ضربت الستوب (SL)**\n🪙 GOLD | السعر: `{price:.2f}`\n📉 النقاط: `{pips_lost}` Pip"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp2:
                pips_gained = round((tp2 - entry) * 10, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = f"🎯🎯 **تم ضرب الهدف الثاني بنجاح (TP2)!**\n🪙 GOLD | السعر: `{price:.2f}`\n📈 الأرباح الكاملة: `{pips_gained}` Pip"
                active_trade = None
                return "UPDATE", msg
            elif price >= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                pips_gained = round((tp1 - entry) * 10, 1)
                msg = (
                    f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n"
                    f"💰 **توصية:** إغلاق 50% من العقود ونقل الستوب لنقطة الدخول (`{entry:.2f}`)."
                )
                return "UPDATE", msg

        elif trade_type == "SELL":
            if price >= sl:
                pips_lost = round((entry - sl) * 10, 1)
                daily_stats["losses"] += 1
                daily_stats["total_pips"] += pips_lost
                msg = f"❌ **ضربت الستوب (SL)**\n🪙 GOLD | السعر: `{price:.2f}`\n📉 النقاط: `{pips_lost}` Pip"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp2:
                pips_gained = round((entry - tp2) * 10, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = f"🎯🎯 **تم ضرب الهدف الثاني بنجاح (TP2)!**\n🪙 GOLD | السعر: `{price:.2f}`\n📈 الأرباح الكاملة: `{pips_gained}` Pip"
                active_trade = None
                return "UPDATE", msg
            elif price <= tp1 and not active_trade.get("tp1_hit"):
                active_trade["tp1_hit"] = True
                pips_gained = round((entry - tp1) * 10, 1)
                msg = (
                    f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n"
                    f"💰 **توصية:** إغلاق 50% من العقود ونقل الستوب لنقطة الدخول (`{entry:.2f}`)."
                )
                return "UPDATE", msg

        return None, None

    # 2. فحص الأخبار الاقتصادية قبل فتح صفقة جديدة
    has_news, news_title = is_news_time()
    if has_news:
        print(f"Skipping trade due to high impact news: {news_title}")
        return None, None

    # 3. تحليل SMC الفني الصافي
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

    daily_stats["total_trades"] += 1
    signal_emoji = "🟢" if trade == "BUY" else "🔴"

    message = f"""{signal_emoji} **{trade}**

📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف الأول:** `{tp1:.2f}`
🎯 **الهدف الثاني:** `{tp2:.2f}`

🛡️ **الستوب:** `{sl:.2f}`
"""
    return "NEW_TRADE", message

async def send_daily_summary():
    """إرسال التقرير اليومي التلقائي مع نهاية اليوم"""
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
            text="⚡ تم تشغيل البوت بنظام SMC (مع فلتر الأخبار + الإغلاق الجزئي + التقرير اليومي) بنجاح!"
        )
    except Exception as e:
        print(f"Telegram Error: {e}")

    last_hourly_report = datetime.now()
    daily_summary_sent_today = False

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

            # إرسال التقرير اليومي عند الساعة 23:55 ليلاً
            if now.hour == 23 and now.minute >= 55 and not daily_summary_sent_today:
                await send_daily_summary()
                daily_summary_sent_today = True

            # إعادة ضبط إرسال التقرير اليومي عند بداية يوم جديد
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

        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
