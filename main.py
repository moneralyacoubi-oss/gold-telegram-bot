import asyncio
from datetime import datetime
import requests
import pandas as pd
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

# مفتاح API مباشر مع تنظيف المسافات تلقائياً
RAW_API_KEY = "cfbd0d0216a94e3c8affdf990d0a14a7"
API_KEY = RAW_API_KEY.strip()

last_signal = None
active_trade = None
last_trade_time = datetime.now()
last_trade_closed_time = datetime.now()

daily_stats = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_pips": 0.0,
    "last_reset_date": datetime.now().date()
}

def get_chart_url():
    return "https://charts2.finviz.com/chart.ashx?t=GOLD&tf=m5"

def is_news_time():
    try:
        url = "https://nws.forexfactory1.com/forex_calendar.json"
        res = requests.get(url, timeout=4).json()
        now = datetime.now()
        
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
    today = datetime.now().date()
    if daily_stats["last_reset_date"] != today:
        daily_stats = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pips": 0.0,
            "last_reset_date": today
        }

def fetch_data(timeframe, outputsize=50):
    url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={timeframe}&outputsize={outputsize}&apikey={API_KEY}"
    try:
        res = requests.get(url, timeout=8).json()
        if "values" not in res:
            print(f"⚠️ API Response Error: {res}")
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

def detect_fast_signals(df):
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]

    last_close = closes.iloc[-1]

    recent_high = highs.tail(5).iloc[:-1].max()
    recent_low = lows.tail(5).iloc[:-1].min()

    bos_bullish = last_close > recent_high
    bos_bearish = last_close < recent_low

    sl_buy = lows.tail(3).min()
    sl_sell = highs.tail(3).max()

    return {
        "bos_bullish": bos_bullish,
        "bos_bearish": bos_bearish,
        "sl_buy": sl_buy,
        "sl_sell": sl_sell
    }

def check_signal():
    global last_signal, active_trade, last_trade_time, daily_stats, last_trade_closed_time

    reset_daily_stats_if_needed()

    df_m5 = fetch_data("5min", 40)

    if df_m5 is None:
        return None, None, None

    close = df_m5["close"]
    price = float(close.iloc[-1])
    
    print(f"🔍 [تحليل حي] سعر الذهب الحالي: {price:.2f} | الوقت: {datetime.now().strftime('%H:%M:%S')}")

    if active_trade:
        trade_type = active_trade["type"]
        entry = active_trade["entry"]
        tp1 = active_trade["tp1"]
        sl = active_trade["sl"]
        entry_time = active_trade.get("entry_time", datetime.now())

        time_elapsed = (datetime.now() - entry_time).total_seconds() / 60.0
        if time_elapsed >= 120:
            msg = f"⏳ **إلغاء متابعة صفقة ({trade_type})**\nسبب الإلغاء: بطء الحركة وتذبذب السعر لأكثر من ساعتين.\n⚡ البوت متفرغ الآن لفرص جديدة."
            active_trade = None
            last_trade_closed_time = datetime.now()
            return "UPDATE", msg, None

        if trade_type == "BUY":
            if price <= sl:
                pips_lost = round((sl - entry) * 10, 1)
                daily_stats["losses"] += 1
                daily_stats["total_pips"] += pips_lost
                msg = f"❌ **ضربت الستوب (SL)**\n🪙 GOLD | السعر: `{price:.2f}`\n📉 النقاط: `{pips_lost}` Pip"
                active_trade = None
                last_trade_closed_time = datetime.now()
                return "UPDATE", msg, None
            elif price >= tp1:
                pips_gained = round((tp1 - entry) * 10, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = (
                    f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n"
                    f"💰 **توصية:** إغلاق 50% ونقل الستوب لنقطة الدخول (`{entry:.2f}`).\n"
                    f"⚡ البوت متاح الآن لاستقبال أي صفقة جديدة."
                )
                active_trade = None
                last_trade_closed_time = datetime.now()
                return "UPDATE", msg, None

        elif trade_type == "SELL":
            if price >= sl:
                pips_lost = round((entry - sl) * 10, 1)
                daily_stats["losses"] += 1
                daily_stats["total_pips"] += pips_lost
                msg = f"❌ **ضربت الستوب (SL)**\n🪙 GOLD | السعر: `{price:.2f}`\n📉 النقاط: `{pips_lost}` Pip"
                active_trade = None
                last_trade_closed_time = datetime.now()
                return "UPDATE", msg, None
            elif price <= tp1:
                pips_gained = round((entry - tp1) * 10, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = (
                    f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n"
                    f"💰 **توصية:** إغلاق 50% ونقل الستوب لنقطة الدخول (`{entry:.2f}`).\n"
                    f"⚡ البوت متاح الآن لاستقبال أي صفقة جديدة."
                )
                active_trade = None
                last_trade_closed_time = datetime.now()
                return "UPDATE", msg, None

        return None, None, None

    # مهلة 10 دقائق بعد إغلاق أي صفقة
    cooldown_minutes = (datetime.now() - last_trade_closed_time).total_seconds() / 60.0
    if cooldown_minutes < 10:
        return None, None, None

    has_news, news_title = is_news_time()
    if has_news:
        print(f"🛑 تجنب الدخول بسبب الأخبار: {news_title}")
        return None, None, None

    signals = detect_fast_signals(df_m5)

    trade = None
    sl = 0

    if signals["bos_bullish"]:
        trade = "BUY"
        sl = signals["sl_buy"] - 0.30
        risk = price - sl
        if risk <= 0: return None, None, None
        tp1 = price + (risk * 1.2)
        tp2 = price + (risk * 2.5)

    elif signals["bos_bearish"]:
        trade = "SELL"
        sl = signals["sl_sell"] + 0.30
        risk = sl - price
        if risk <= 0: return None, None, None
        tp1 = price - (risk * 1.2)
        tp2 = price - (risk * 2.5)
    else:
        return None, None, None

    current_signal = f"{trade}_{round(price, 2)}"
    if current_signal == last_signal:
        return None, None, None

    last_signal = current_signal
    last_trade_time = datetime.now()

    entry = price
    active_trade = {
        "type": trade,
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "entry_time": datetime.now()
    }

    daily_stats["total_trades"] += 1
    signal_emoji = "🟢" if trade == "BUY" else "🔴"

    message = f"""{signal_emoji} **{trade}**

📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف الأول:** `{tp1:.2f}`
🎯 **الهدف الثاني:** `{tp2:.2f}`

🛡️ **الستوب:** `{sl:.2f}`
"""
    chart_image = get_chart_url()
    return "NEW_TRADE", message, chart_image

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
            text="⚡ تم تشغيل النسخة المستقرة (فصل 10 دقائق بين الصفقات + مفتاح معالج)."
        )
    except Exception as e:
        print(f"Telegram Error: {e}")

    last_hourly_report = datetime.now()
    daily_summary_sent_today = False

    while True:
        try:
            status, msg, chart_img = check_signal()
            if msg:
                if status == "NEW_TRADE" and chart_img:
                    try:
                        await bot.send_photo(
                            chat_id=CHAT_ID,
                            photo=chart_img,
                            caption=msg,
                            parse_mode="Markdown"
                        )
                    except Exception:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            parse_mode="Markdown"
                        )
                else:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        parse_mode="Markdown"
                    )

            now = datetime.now()
            time_since_last_report = (now - last_hourly_report).total_seconds()
            time_since_last_trade = (now - last_trade_time).total_seconds()

            local_hour = (now.hour + 3) % 24

            if local_hour == 23 and now.minute >= 55 and not daily_summary_sent_today:
                await send_daily_summary()
                daily_summary_sent_today = True

            if local_hour == 0 and now.minute < 5:
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

        await asyncio.sleep(45)

if __name__ == "__main__":
    asyncio.run(main())
