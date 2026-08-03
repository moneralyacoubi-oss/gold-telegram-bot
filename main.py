import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

API_KEYS = [
    "cf02fa8d0b10466496bfae35bc8e61fc", "cf6fff5cc5b9481e9b66b0b4557be3e0", "5ab47caa0b614f56ba9815778f0024cb", "c365534f82cf41a7a7e72df8fa9c7637", "7b13e064b5f6406e9a98e78777c5ea91",
    "541bef3becfb4d45a7ead575f147d407", "cc82a74ca22c4b8d8f95f9ab7132b8b9", "6b3970b4f67d4b68a6e26d2b5357373b", "18d552240c38461da8eb89be259b2250", "7d34370b5fbf4160a6b04f07ede97648"
]

current_key_index = 0

def get_next_api_key():
    global current_key_index
    key = API_KEYS[current_key_index].strip()
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    return key

IRAQ_TZ = pytz.timezone("Asia/Baghdad")

def get_now():
    return datetime.now(IRAQ_TZ)

# قائمة العملات والأصول (وسّعنا القائمة لتزيد الفرص)
SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "BTC/USD"]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: get_now() for s in SYMBOLS}

daily_stats = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_pips": 0.0,
    "last_reset_date": get_now().date()
}

def is_high_liquidity_session(symbol):
    now = get_now()
    if now.weekday() in [5, 6]:  # حظر الويكند
        return False
    hour = now.hour
    return 10 <= hour <= 23  # جلسة عمل واسعة (لندن + نيويورك)

def fetch_data(symbol, timeframe, outputsize=100):
    api_key = get_next_api_key()
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize={outputsize}&apikey={api_key}"
    try:
        res = requests.get(url, timeout=8).json()
        if "values" not in res:
            return None
        df = pd.DataFrame(res["values"]).iloc[::-1]
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

def detect_fvg_ict_signals(df_m5, df_h1):
    """خوارزمية سريعة ومضبوطة: H1 Bias + M5 FVG Breakout"""
    h1_closes = df_h1["close"]
    h1_ema = h1_closes.ewm(span=30, adjust=False).mean().iloc[-1]
    
    # اتجاه فريم الساعة H1
    h1_bias = "BULLISH" if h1_closes.iloc[-1] > h1_ema else "BEARISH"

    m5_highs = df_m5["high"].values
    m5_lows = df_m5["low"].values
    m5_closes = df_m5["close"].values

    # كشف فجوة FVG
    fvg_bullish = m5_lows[-1] > m5_highs[-3]
    fvg_bearish = m5_highs[-1] < m5_lows[-3]

    # سيولة مرنة (10 شموع سابقة)
    recent_high = max(m5_highs[-10:-2])
    recent_low = min(m5_lows[-10:-2])

    swept_low = min(m5_lows[-4:-1]) <= recent_low
    swept_high = max(m5_highs[-4:-1]) >= recent_high

    buy_signal = False
    sell_signal = False

    # شروط دخول مرنة وقوية
    if h1_bias == "BULLISH" and (swept_low or fvg_bullish):
        if m5_closes[-1] > m5_closes[-2]:
            buy_signal = True

    if h1_bias == "BEARISH" and (swept_high or fvg_bearish):
        if m5_closes[-1] < m5_closes[-2]:
            sell_signal = True

    return {
        "buy": buy_signal,
        "sell": sell_signal,
        "sl_buy": min(m5_lows[-4:]),
        "sl_sell": max(m5_highs[-4:])
    }

def get_pip_multiplier(symbol):
    if "BTC" in symbol:
        return 1.0
    elif "XAU" in symbol:
        return 10.0
    elif "JPY" in symbol:
        return 100.0
    else:
        return 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, daily_stats, last_trade_closed_times

    if not is_high_liquidity_session(symbol):
        return None, None

    df_m5 = fetch_data(symbol, "5min", 80)
    df_h1 = fetch_data(symbol, "1h", 60)

    if df_m5 is None or df_h1 is None or len(df_m5) < 20 or len(df_h1) < 30:
        return None, None

    price = float(df_m5["close"].iloc[-1])
    now = get_now()
    pip_mult = get_pip_multiplier(symbol)

    active_trade = active_trades[symbol]

    # متابعة وإغلاق الصفقة الحالية
    if active_trade:
        trade_type = active_trade["type"]
        entry = active_trade["entry"]
        tp1 = active_trade["tp1"]
        sl = active_trade["sl"]

        if trade_type == "BUY":
            if price <= sl:
                pips = round((sl - entry) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit_label = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"❌ **إغلاق على خسارة (SL)**\n📉 {symbol} | `{pips}` {unit_label}"
            elif price >= tp1:
                pips = round((tp1 - entry) * pip_mult, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit_label = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف (TP)!** (+{pips} {unit_label})\n📊 {symbol}"

        elif trade_type == "SELL":
            if price >= sl:
                pips = round((entry - sl) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit_label = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"❌ **إغلاق على خسارة (SL)**\n📉 {symbol} | `{pips}` {unit_label}"
            elif price <= tp1:
                pips = round((entry - tp1) * pip_mult, 1)
                daily_stats["wins"] += 1
                daily_stats["total_pips"] += pips
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit_label = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف (TP)!** (+{pips} {unit_label})\n📊 {symbol}"

        return None, None

    # فترة انتظار 15 دقيقة بين صفقة وأخرى لنفس الزوج
    cooldown = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown < 15:
        return None, None

    signals = detect_fvg_ict_signals(df_m5, df_h1)

    trade = None
    if "BTC" in symbol:
        sl_dist = 120.0
    elif "XAU" in symbol:
        sl_dist = 0.70
    elif "JPY" in symbol:
        sl_dist = 0.15
    else:
        sl_dist = 0.0015

    if signals["buy"]:
        trade = "BUY"
        sl = signals["sl_buy"] - sl_dist
        risk = price - sl
        if risk <= 0: return None, None
        tp1 = price + (risk * 2.0)

    elif signals["sell"]:
        trade = "SELL"
        sl = signals["sl_sell"] + sl_dist
        risk = sl - price
        if risk <= 0: return None, None
        tp1 = price - (risk * 2.0)
    else:
        return None, None

    current_signal = f"{trade}_{round(price, 2)}"
    if current_signal == last_signals[symbol]:
        return None, None

    last_signals[symbol] = current_signal
    entry = price
    active_trades[symbol] = {
        "type": trade,
        "entry": entry,
        "tp1": tp1,
        "sl": sl,
        "entry_time": now
    }

    daily_stats["total_trades"] += 1
    emoji = "🟢 BUY" if trade == "BUY" else "🔴 SELL"
    
    if "BTC" in symbol:
        tv_symbol = "BINANCE:BTCUSDT"
    elif "XAU" in symbol:
        tv_symbol = "OANDA:XAUUSD"
    elif "GBP" in symbol:
        tv_symbol = "FX:GBPUSD"
    elif "JPY" in symbol:
        tv_symbol = "FX:USDJPY"
    else:
        tv_symbol = "FX:EURUSD"

    message = f"""{emoji} **إشارة جديدة (H1 Bias + FVG Fast)**

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف (RR 1:2):** `{tp1:.2f}`
🛡️ **الستوب المحمي:** `{sl:.2f}`

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def main():
    print("🚀 جاري تشغيل الخوارزمية المحدثة (5 أزواج + سرعة لقط الصفقات)...", flush=True)

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

        except Exception as e:
            print(f"Loop Error: {e}", flush=True)

        await asyncio.sleep(35)

if __name__ == "__main__":
    asyncio.run(main())
