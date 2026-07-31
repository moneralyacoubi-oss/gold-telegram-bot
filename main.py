import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

# ⚠️ ضع المفاتيح الـ 10 هنا
API_KEYS = [
    "cf02fa8d0b10466496bfae35bc8e61fc",
    "cf6fff5cc5b9481e9b66b0b4557be3e0",
    "5ab47caa0b614f56ba9815778f0024cb",
    "7b13e064b5f6406e9a98e78777c5ea91",
    "c365534f82cf41a7a7e72df8fa9c7637",
    "541bef3becfb4d45a7ead575f147d407",
    "cc82a74ca22c4b8d8f95f9ab7132b8b9",
    "6b3970b4f67d4b68a6e26d2b5357373b",
    "18d552240c38461da8eb89be259b2250",
    "7d34370b5fbf4160a6b04f07ede97648"
]

current_key_index = 0

def get_next_api_key():
    global current_key_index
    key = API_KEYS[current_key_index].strip()
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    return key

# ضبط التوقيت المحلي على بغداد (UTC+3)
IRAQ_TZ = pytz.timezone("Asia/Baghdad")

def get_now():
    return datetime.now(IRAQ_TZ)

SYMBOLS = ["XAU/USD", "EUR/USD"]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: get_now() for s in SYMBOLS}

last_trade_time = get_now()

daily_stats = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_pips": 0.0,
    "last_reset_date": get_now().date()
}

def is_high_liquidity_session():
    """التحقق من جلسات التداول القوية (لندن ونيويورك) بتوقيت بغداد"""
    now = get_now()
    hour = now.hour
    # جلسة لندن (10 ص - 6 م) وجلسة نيويورك (3:30 م - 11 م)
    if 10 <= hour <= 23:
        return True
    return False

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

def fetch_data(symbol, timeframe, outputsize=100):
    api_key = get_next_api_key()
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize={outputsize}&apikey={api_key}"
    try:
        res = requests.get(url, timeout=8).json()
        if "values" not in res:
            print(f"⚠️ API Error ({symbol} - {timeframe}) مع المفتاح: {res}", flush=True)
            return None
        df = pd.DataFrame(res["values"]).iloc[::-1]
        df["close"] = df["close"].astype(float)
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching {symbol} {timeframe}: {e}", flush=True)
        return None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def detect_advanced_smc_signals(df_m5, df_h1):
    """خوارزمية SMC المتقدمة: اتجاه هرمي + سحب سيولة + كسر حقيقي"""
    h1_closes = df_h1["close"]
    h1_ema200 = h1_closes.ewm(span=200, adjust=False).mean().iloc[-1]
    h1_last_close = h1_closes.iloc[-1]
    
    h1_is_uptrend = h1_last_close > h1_ema200
    h1_is_downtrend = h1_last_close < h1_ema200

    m5_closes = df_m5["close"]
    m5_highs = df_m5["high"]
    m5_lows = df_m5["low"]

    m5_last_close = m5_closes.iloc[-1]
    m5_prev_close = m5_closes.iloc[-2]
    m5_ema200 = m5_closes.ewm(span=200, adjust=False).mean().iloc[-1]
    rsi = calculate_rsi(m5_closes, 14).iloc[-1]

    # تحديد أعلى قمة وأقل قاع في آخر 10 شمعات
    recent_high = m5_highs.tail(10).iloc[:-2].max()
    recent_low = m5_lows.tail(10).iloc[:-2].min()

    # شرط سحب السيولة (Liquidity Sweep): السعر ضرب القمة/القاع وعاد بالإغلاق فوق/تحت
    sweep_bullish = (df_m5["low"].iloc[-2] < recent_low) and (m5_prev_close > recent_low)
    sweep_bearish = (df_m5["high"].iloc[-2] > recent_high) and (m5_prev_close < recent_high)

    # شروط دخول صريحة ومحكمة
    bos_bullish = (m5_last_close > recent_high) and (m5_last_close > m5_ema200) and h1_is_uptrend and (rsi < 68) and not sweep_bearish
    bos_bearish = (m5_last_close < recent_low) and (m5_last_close < m5_ema200) and h1_is_downtrend and (rsi > 32) and not sweep_bullish

    return {
        "bos_bullish": bos_bullish,
        "bos_bearish": bos_bearish,
        "sl_buy": m5_lows.tail(5).min(),
        "sl_sell": m5_highs.tail(5).max()
    }

def get_pip_multiplier(symbol):
    return 10.0 if "XAU" in symbol else 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_time, daily_stats, last_trade_closed_times

    reset_daily_stats_if_needed()

    # إلغاء الصفقات خارج أوقات السيولة المرتفعة
    if not is_high_liquidity_session():
        return None, None

    df_m5 = fetch_data(symbol, "5min", 100)
    df_h1 = fetch_data(symbol, "1h", 210)

    if df_m5 is None or df_h1 is None or len(df_m5) < 50 or len(df_h1) < 200:
        return None, None

    close = df_m5["close"]
    price = float(close.iloc[-1])
    now = get_now()
    pip_mult = get_pip_multiplier(symbol)

    print(f"⚡ [تحليل SMC ذكي] {symbol} | السعر: {price:.4f} | الوقت: {now.strftime('%H:%M:%S')}", flush=True)

    active_trade = active_trades[symbol]

    if active_trade:
        trade_type = active_trade["type"]
        entry = active_trade["entry"]
        tp1 = active_trade["tp1"]
        sl = active_trade["sl"]
        is_be_moved = active_trade.get("be_moved", False)
        entry_time = active_trade.get("entry_time", now)

        be_trigger_pips = 18.0 if "XAU" in symbol else 12.0

        if trade_type == "BUY":
            current_gain_pips = (price - entry) * pip_mult
            if current_gain_pips >= be_trigger_pips and not is_be_moved:
                active_trades[symbol]["sl"] = entry
                active_trades[symbol]["be_moved"] = True
                msg = (
                    f"🛡️ **تأمين الصفقة تلقائياً (Breakeven)!**\n"
                    f"الرمز: **{symbol}** | النوع: **BUY**\n"
                    f"💡 **حققت الصفقة +{be_trigger_pips} نقطة:** تم نقل الستوب لنقطة الدخول (`{entry:.4f}`)."
                )
                return "UPDATE", msg

            if price <= active_trades[symbol]["sl"]:
                pips_result = round((active_trades[symbol]["sl"] - entry) * pip_mult, 1)
                msg = f"⚖️ **إغلاق الدخول (BE)**" if pips_result >= 0 else f"❌ **ضربت الستوب (SL)**\n📉 الخسارة: `{pips_result}` Pip"
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                return "UPDATE", msg

            elif price >= tp1:
                pips_gained = round((tp1 - entry) * pip_mult, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n📊 **الرمز:** {symbol}"
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                return "UPDATE", msg

        elif trade_type == "SELL":
            current_gain_pips = (entry - price) * pip_mult
            if current_gain_pips >= be_trigger_pips and not is_be_moved:
                active_trades[symbol]["sl"] = entry
                active_trades[symbol]["be_moved"] = True
                msg = (
                    f"🛡️ **تأمين الصفقة تلقائياً (Breakeven)!**\n"
                    f"الرمز: **{symbol}** | النوع: **SELL**\n"
                    f"💡 **حققت الصفقة +{be_trigger_pips} نقطة:** تم نقل الستوب لنقطة الدخول (`{entry:.4f}`)."
                )
                return "UPDATE", msg

            if price >= active_trades[symbol]["sl"]:
                pips_result = round((entry - active_trades[symbol]["sl"]) * pip_mult, 1)
                msg = f"⚖️ **إغلاق الدخول (BE)**" if pips_result >= 0 else f"❌ **ضربت الستوب (SL)**\n📉 الخسارة: `{pips_result}` Pip"
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                return "UPDATE", msg

            elif price <= tp1:
                pips_gained = round((entry - tp1) * pip_mult, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips_gained
                msg = f"🎯 **تحقق الهدف الأول (TP1)!** (+{pips_gained} Pip)\n📊 **الرمز:** {symbol}"
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                return "UPDATE", msg

        time_elapsed = (now - entry_time).total_seconds() / 60.0
        if time_elapsed >= 120:
            diff_pips = round(((price - entry) if trade_type == "BUY" else (entry - price)) * pip_mult, 1)
            advice = f"بربح (+{diff_pips} Pip) 🟢" if diff_pips > 0 else f"بخسارة ({diff_pips} Pip) 🔴"
            msg = f"⏳ **إغلاق زمني (ساعتين):** {symbol} | اخرجوا **{advice}**"
            active_trades[symbol] = None
            last_trade_closed_times[symbol] = now
            return "UPDATE", msg

        return None, None

    cooldown_minutes = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown_minutes < 15:
        return None, None

    has_news, news_title = is_news_time()
    if has_news:
        return None, None

    signals = detect_advanced_smc_signals(df_m5, df_h1)

    trade = None
    sl = 0
    sl_buffer = 0.45 if "XAU" in symbol else 0.0014

    if signals["bos_bullish"]:
        trade = "BUY"
        sl = signals["sl_buy"] - sl_buffer
        risk = price - sl
        if risk <= 0: return None, None
        tp1 = price + (risk * 1.5)
        tp2 = price + (risk * 2.5)

    elif signals["bos_bearish"]:
        trade = "SELL"
        sl = signals["sl_sell"] + sl_buffer
        risk = sl - price
        if risk <= 0: return None, None
        tp1 = price - (risk * 1.5)
        tp2 = price - (risk * 2.5)
    else:
        return None, None

    current_signal = f"{trade}_{round(price, 4)}"
    if current_signal == last_signals[symbol]:
        return None, None

    last_signals[symbol] = current_signal
    last_trade_time = now

    entry = price
    active_trades[symbol] = {
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
    tv_symbol = "OANDA:XAUUSD" if "XAU" in symbol else "FX:EURUSD"

    message = f"""{signal_emoji} **{trade}** ({symbol}) [إشارة SMC فائقة]

📍 **سعر الدخول:** `{entry:.4f}`

🎯 **الهدف الأول:** `{tp1:.4f}`
🎯 **الهدف الثاني:** `{tp2:.4f}`

🛡️ **الستوب المحمي:** `{sl:.4f}`

📈 [عرض الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def send_daily_summary():
    pips = daily_stats["total_pips"]
    pips_str = f"+{pips:.1f}" if pips >= 0 else f"{pips:.1f}"
    summary_msg = f"📊 **تقرير اليوم:** صفقات `{daily_stats['total_trades']}` | نقاط `{pips_str}` Pips"
    try:
        await bot.send_message(chat_id=CHAT_ID, text=summary_msg, parse_mode="Markdown")
    except Exception:
        pass

async def main():
    global last_trade_time

    print("🚀 البوت المطور يعمل الآن بنظام SMC الذكي والجلسات الفعالة...", flush=True)

    last_hourly_report = get_now()
    daily_summary_sent_today = False

    while True:
        try:
            for symbol in SYMBOLS:
                status, msg = process_symbol(symbol)
                if msg:
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=False
                    )
                await asyncio.sleep(2)

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
                    await bot.send_message(chat_id=CHAT_ID, text="بعد ما منير حلل السوك طلع ماكو صفقات حالياً 📊")
                last_hourly_report = now

        except Exception as e:
            print(f"Loop Error: {e}", flush=True)

        # فحص كل 45 ثانية لتغطية اليوم الكامل (24 ساعة) بـ 10 مفاتيح
        await asyncio.sleep(45)

if __name__ == "__main__":
    asyncio.run(main())
