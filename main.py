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

SYMBOLS = ["XAU/USD", "EUR/USD", "BTC/USD"]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: get_now() for s in SYMBOLS}

def is_high_liquidity_session():
    now = get_now()
    if now.weekday() in [5, 6]:
        return False
    hour = now.hour
    return 11 <= hour <= 22

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

def calculate_atr(df, period=14):
    """حساب مؤشر ATR للتذبذب الديناميكي"""
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    atr = df['tr'].rolling(window=period).mean().iloc[-1]
    return atr

def detect_advanced_institutional_signals(df_m5, df_h1, symbol):
    """خوارزمية مؤسسية V3.0: هيكل H1 + سيولة قوية + ATR ديناميكي + Displacement FVG"""
    
    # 1. هيكل السوق H1 (Market Structure) بدون مؤشرات
    h1_highs = df_h1["high"].values
    h1_lows = df_h1["low"].values
    
    # اتجاه هيكلي صريح
    h1_bullish_structure = h1_highs[-1] > h1_highs[-3] and h1_lows[-1] > h1_lows[-3]
    h1_bearish_structure = h1_highs[-1] < h1_highs[-3] and h1_lows[-1] < h1_lows[-3]

    m5_highs = df_m5["high"].values
    m5_lows = df_m5["low"].values
    m5_closes = df_m5["close"].values
    m5_opens = df_m5["open"].values

    # 2. سحب سيولة قوية لـ 50 شمعة (Major Liquidity Sweep)
    major_high = max(m5_highs[-50:-3])
    major_low = min(m5_lows[-50:-3])

    swept_low = min(m5_lows[-4:-1]) < major_low
    swept_high = max(m5_highs[-4:-1]) > major_high

    # 3. التأكد من إغلاق الشمعة
    prev_closed_bullish = m5_closes[-2] > m5_opens[-2]
    prev_closed_bearish = m5_closes[-2] < m5_opens[-2]

    # 4. FVG مع اندفاع قوي (Displacement)
    fvg_bullish_gap = m5_lows[-2] - m5_highs[-4]
    fvg_bearish_gap = m5_lows[-4] - m5_highs[-2]
    
    # قياس حجم الفجوة بالنسبة للتذبذب
    atr = calculate_atr(df_m5)
    valid_fvg_bull = fvg_bullish_gap > (atr * 0.15)
    valid_fvg_bear = fvg_bearish_gap > (atr * 0.15)

    buy_signal = False
    sell_signal = False

    if h1_bullish_structure and swept_low and valid_fvg_bull and prev_closed_bullish:
        buy_signal = True

    if h1_bearish_structure and swept_high and valid_fvg_bear and prev_closed_bearish:
        sell_signal = True

    return {
        "buy": buy_signal,
        "sell": sell_signal,
        "atr": atr,
        "sl_buy": min(m5_lows[-5:-1]),
        "sl_sell": max(m5_highs[-5:-1])
    }

def get_pip_multiplier(symbol):
    if "BTC" in symbol: return 1.0
    elif "XAU" in symbol: return 10.0
    else: return 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_closed_times

    if not is_high_liquidity_session():
        return None, None

    df_m5 = fetch_data(symbol, "5min", 100)
    df_h1 = fetch_data(symbol, "1h", 60)

    if df_m5 is None or df_h1 is None or len(df_m5) < 55 or len(df_h1) < 50:
        return None, None

    price = float(df_m5["close"].iloc[-1])
    now = get_now()
    pip_mult = get_pip_multiplier(symbol)

    active_trade = active_trades[symbol]

    # متابعة الصفقة
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
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"❌ **إغلاق على خسارة (SL)**\n📉 {symbol} | `{pips}` {unit}"
            elif price >= tp1:
                pips = round((tp1 - entry) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف (TP)!** (+{pips} {unit})\n📊 {symbol}"

        elif trade_type == "SELL":
            if price >= sl:
                pips = round((entry - sl) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"❌ **إغلاق على خسارة (SL)**\n📉 {symbol} | `{pips}` {unit}"
            elif price <= tp1:
                pips = round((entry - tp1) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف (TP)!** (+{pips} {unit})\n📊 {symbol}"

        return None, None

    # فترة انتظار 45 دقيقة بعد الخسارة/الربح
    cooldown = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown < 45:
        return None, None

    signals = detect_advanced_institutional_signals(df_m5, df_h1, symbol)
    atr = signals["atr"]

    # حساب الستوب والهدف هيدروليكياً باستخدام ATR
    if signals["buy"]:
        trade = "BUY"
        sl = signals["sl_buy"] - (atr * 0.5) # ستوب محمي مع ATR
        risk = price - sl
        if risk <= 0: return None, None
        tp1 = price + (risk * 2.0)

    elif signals["sell"]:
        trade = "SELL"
        sl = signals["sl_sell"] + (atr * 0.5) # ستوب محمي مع ATR
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

    emoji = "🟢 BUY" if trade == "BUY" else "🔴 SELL"
    tv_symbol = "BINANCE:BTCUSDT" if "BTC" in symbol else ("OANDA:XAUUSD" if "XAU" in symbol else "FX:EURUSD")

    message = f"""{emoji} **إشارة مؤسسية متقدمة (V3.0)**

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف (RR 1:2):** `{tp1:.2f}`
🛡️ **الستوب الديناميكي (ATR):** `{sl:.2f}`

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def main():
    print("🚀 جاري تشغيل النسخة المؤسسية المتقدمة V3.0...", flush=True)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="🔥 **تم رفع التحديث V3.0 بنجاح:**\nتم تفعيل الستوب الديناميكي (ATR) + الهيكل H1 بدون مؤشرات + تصفية السيولة الكبرى (50 شمعة).",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Telegram Test Error: {e}", flush=True)

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

        await asyncio.sleep(40)

if __name__ == "__main__":
    asyncio.run(main())
