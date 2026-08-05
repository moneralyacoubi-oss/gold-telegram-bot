import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

API_KEYS = [
    "KEY_1", "KEY_2", "KEY_3", "KEY_4", "KEY_5",
    "KEY_6", "KEY_7", "KEY_8", "KEY_9", "KEY_10"
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

# توسيع قائمة الأزواج لزيادة الفرص اليومية
SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "BTC/USD"]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: get_now() for s in SYMBOLS}

def is_high_liquidity_session():
    now = get_now()
    if now.weekday() in [5, 6]:
        return False
    hour = now.hour
    return 10 <= hour <= 23  # تغطية أوسع لجلسات لندن ونيويورك

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
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    return df['tr'].rolling(window=period).mean().iloc[-1]

def detect_high_precision_signals(df_tf, df_h1):
    """خوارزمية الفحص المتقدمة على الفريمات السريعة (M3 / M5)"""
    h1_highs = df_h1["high"].values
    h1_lows = df_h1["low"].values
    
    # هيكل H1 الصريح
    h1_bullish = h1_highs[-1] > h1_highs[-3] and h1_lows[-1] > h1_lows[-3]
    h1_bearish = h1_highs[-1] < h1_highs[-3] and h1_lows[-1] < h1_lows[-3]

    highs = df_tf["high"].values
    lows = df_tf["low"].values
    closes = df_tf["close"].values
    opens = df_tf["open"].values

    # سحب سيولة قمم/قيعان رئيسية لـ 35 شمعة
    major_high = max(highs[-35:-3])
    major_low = min(lows[-35:-3])

    swept_low = min(lows[-3:-1]) < major_low
    swept_high = max(highs[-3:-1]) > major_high

    prev_bullish = closes[-2] > opens[-2]
    prev_bearish = closes[-2] < opens[-2]

    # فجوة FVG اندفاعية
    fvg_bull = lows[-2] - highs[-4]
    fvg_bear = lows[-4] - highs[-2]
    
    atr = calculate_atr(df_tf)
    valid_fvg_bull = fvg_bull > (atr * 0.12)
    valid_fvg_bear = fvg_bear > (atr * 0.12)

    buy_signal = h1_bullish and swept_low and valid_fvg_bull and prev_bullish
    sell_signal = h1_bearish and swept_high and valid_fvg_bear and prev_bearish

    return {
        "buy": buy_signal,
        "sell": sell_signal,
        "atr": atr,
        "fvg_entry_buy": highs[-4], # مدخل من قمة FVG
        "fvg_entry_sell": lows[-4], # مدخل من قاع FVG
        "sl_buy": min(lows[-5:-1]),
        "sl_sell": max(highs[-5:-1])
    }

def get_pip_multiplier(symbol):
    if "BTC" in symbol: return 1.0
    elif "XAU" in symbol or "JPY" in symbol: return 10.0
    else: return 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_closed_times

    if not is_high_liquidity_session():
        return None, None

    # استخدام فريم 3min للالتقاط السريع، مع فريم H1 للاتجاه
    df_m3 = fetch_data(symbol, "3min", 80)
    df_h1 = fetch_data(symbol, "1h", 50)

    if df_m3 is None or df_h1 is None or len(df_m3) < 40 or len(df_h1) < 40:
        return None, None

    price = float(df_m3["close"].iloc[-1])
    now = get_now()
    pip_mult = get_pip_multiplier(symbol)

    active_trade = active_trades[symbol]

    # إدارة صفقات مفتوحة
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

    # فترة تبريد بين الصفقات (30 دقيقة للزوج الواحد)
    cooldown = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown < 30:
        return None, None

    signals = detect_high_precision_signals(df_m3, df_h1)
    atr = signals["atr"]

    if signals["buy"]:
        trade = "BUY"
        sl = signals["sl_buy"] - (atr * 0.4)
        risk = price - sl
        if risk <= 0: return None, None
        tp1 = price + (risk * 2.2) # زيادة الريسك ريوارد لـ 1:2.2

    elif signals["sell"]:
        trade = "SELL"
        sl = signals["sl_sell"] + (atr * 0.4)
        risk = sl - price
        if risk <= 0: return None, None
        tp1 = price - (risk * 2.2)
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
    tv_symbol = f"FX:{symbol.replace('/', '')}" if "BTC" not in symbol and "XAU" not in symbol else ("OANDA:XAUUSD" if "XAU" in symbol else "BINANCE:BTCUSDT")

    message = f"""{emoji} **إشارة مؤسسية دقيقة (V3.5 Multi-Asset)**

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف (RR 1:2.2):** `{tp1:.2f}`
🛡️ **الستوب المرن (ATR):** `{sl:.2f}`

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def main():
    print("🚀 جاري تشغيل النسخة المتقدمة V3.5 متعددة الأصول...", flush=True)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="⚡ **تم رفع التحديث V3.5 بنجاح:**\nتم تفعيل فريم الـ 3 دقائق + إضافة الباوند والين (5 أزواج) + زيادة نسبة الربح إلى 1:2.2.",
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

        await asyncio.sleep(30) # فحص كل 30 ثانية لتحديث البيانات أسرع

if __name__ == "__main__":
    asyncio.run(main())
