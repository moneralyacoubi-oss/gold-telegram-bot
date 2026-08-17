import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, CHAT_ID

VERSION = "v3.6 (Pro SMC Structure)"

request = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
bot = Bot(token=BOT_TOKEN, request=request)

API_KEYS = [
    "C8229f7582f645b5a6cb09e6e4490002",
    "ba9b9b464937486f953d12278ffc0c54",
    "3aa16ae3bc7d44f28cbf629508c020bf",
    "69b9cd8250344066a54be4108225f849",
    "76a7b6f10798424385db93fe18a56e76",
    "59d7ff4537d846298cc50992950f0082",
    "ff6c85b0a3f14866938d4c43865ce1df",
    "10cbf9b6f30043eb96e3ad2a89063f5f",
    "d3bf745e06f74947a25b2175df9fe178",
    "406452df893f4375a2a79d156f5f66d6",
    "ccfdfdefbd434defaaec9d853680065d",
    "d29ef2928aae41f2b96fcb7ba8b27f3b",
    "ee4ead027117474e8d53a120c8aeb5e5",
    "1edb7d5da95b446dba1a97faf74803eb",
    "56f1f5c2abea4989853d20a452f2dce9",
    "Cf02fa8d0b10466496bfae35bc8e61fc",
    "cf6fff5cc5b9481e9b66b0b4557be3e0",
    "5ab47caa0b614f56ba9815778f0024cb",
    "c365534f82cf41a7a7e72df8fa9c7637",
    "7b13e064b5f6406e9a98e78777c5ea91",
    "541bef3becfb4d45a7ead575f147d407",
    "cc82a74ca22c4b8d8f95f9ab7132b8b9",
    "6b3970b4f67d4b68a6e26d2b5357373b",
    "18d552240c38461da8eb89be259b2250",
    "7d34370b5fbf4160a6b04f07ede97648"
]

active_keys = list(API_KEYS)
current_key_index = 0

def get_next_api_key():
    global current_key_index, active_keys
    if not active_keys:
        return None
    key = active_keys[current_key_index % len(active_keys)].strip()
    current_key_index = (current_key_index + 1) % len(active_keys)
    return key

IRAQ_TZ = pytz.timezone("Asia/Baghdad")

def get_now():
    return datetime.now(IRAQ_TZ)

def is_market_open():
    now = get_now()
    if now.weekday() in [5, 6]:
        return False
    return True

SYMBOLS = [
    "XAU/USD", "BTC/USD", "EUR/USD", "GBP/USD", 
    "GBP/JPY", "EUR/JPY", "AUD/USD", "USD/JPY"
]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: datetime.min.replace(tzinfo=IRAQ_TZ) for s in SYMBOLS}

async def send_telegram_msg(text):
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Telegram Send Error: {e}", flush=True)

def fetch_data(symbol, timeframe, outputsize=50, retries=3):
    global active_keys
    for attempt in range(retries):
        api_key = get_next_api_key()
        if not api_key:
            return None

        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize={outputsize}&apikey={api_key}"
        try:
            res_raw = requests.get(url, timeout=6)
            
            if res_raw.status_code == 401:
                if api_key in active_keys:
                    active_keys.remove(api_key)
                continue

            if res_raw.status_code != 200:
                continue

            try:
                res = res_raw.json()
            except Exception:
                continue

            if "values" in res:
                df = pd.DataFrame(res["values"]).iloc[::-1].reset_index(drop=True)
                for col in ["open", "high", "low", "close"]:
                    df[col] = df[col].astype(float)
                return df
            elif "message" in res and ("run out" in res["message"] or "limit" in res["message"]):
                if api_key in active_keys:
                    active_keys.remove(api_key)
        except Exception as e:
            print(f"API Retry {attempt + 1}/{retries} ({symbol}): {e}", flush=True)
            
    return None

def get_market_bias(symbol):
    df_h1 = fetch_data(symbol, "1h", 20)
    if df_h1 is None or len(df_h1) < 15:
        return "NEUTRAL"
    
    ema_h1 = df_h1['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    price_h1 = df_h1['close'].iloc[-1]
    
    if price_h1 > ema_h1:
        return "BULLISH"
    elif price_h1 < ema_h1:
        return "BEARISH"
    return "NEUTRAL"

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]

def calculate_atr(df, period=14):
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    return df['tr'].rolling(period).mean().iloc[-1]

def detect_fvg(df):
    if len(df) < 3: return None
    if df['low'].iloc[-1] > df['high'].iloc[-3]:
        return "BULLISH_FVG"
    if df['high'].iloc[-1] < df['low'].iloc[-3]:
        return "BEARISH_FVG"
    return None

def detect_smc_signal(df_m5, bias):
    if df_m5 is None or len(df_m5) < 15:
        return None, None

    rsi = calculate_rsi(df_m5)
    atr = calculate_atr(df_m5)
    fvg_type = detect_fvg(df_m5)
    current_price = df_m5['close'].iloc[-1]

    prev_high_m5 = df_m5['high'].iloc[-5:-1].max()
    is_bullish_choch = current_price > prev_high_m5

    prev_low_m5 = df_m5['low'].iloc[-5:-1].min()
    is_bearish_choch = current_price < prev_low_m5

    # فلاتر SMC مع توافق اتجاه H1 Bias
    if bias == "BULLISH" and (rsi < 65) and (is_bullish_choch or fvg_type == "BULLISH_FVG"):
        sl = current_price - (atr * 2.2)
        risk = current_price - sl
        if risk <= 0: return None, None
        tp = current_price + (risk * 2.0)
        return "BUY", {"sl": sl, "tp": tp, "reason": "BULLISH Structure (H1 Bias) + BOS/FVG"}

    if bias == "BEARISH" and (rsi > 35) and (is_bearish_choch or fvg_type == "BEARISH_FVG"):
        sl = current_price + (atr * 2.2)
        risk = sl - current_price
        if risk <= 0: return None, None
        tp = current_price - (risk * 2.0)
        return "SELL", {"sl": sl, "tp": tp, "reason": "BEARISH Structure (H1 Bias) + BOS/FVG"}

    return None, None

def get_pip_multiplier(symbol):
    if "BTC" in symbol: return 1.0
    elif "XAU" in symbol: return 10.0
    elif "JPY" in symbol: return 100.0
    else: return 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_closed_times

    now = get_now()

    if "BTC" not in symbol and not is_market_open():
        return None, None

    df_m5 = fetch_data(symbol, "5min", 30)
    if df_m5 is None:
        return None, None

    price = float(df_m5["close"].iloc[-1])
    pip_mult = get_pip_multiplier(symbol)

    active_trade = active_trades[symbol]

    # إدارة الصفقة المفتوحة
    if active_trade:
        trade_type = active_trade["type"]
        entry = active_trade["entry"]
        tp = active_trade["tp"]
        sl = active_trade["sl"]

        if trade_type == "BUY":
            if price <= sl:
                pips = round((sl - entry) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"❌ **إغلاق: ضرب الستوب (SL)**\n📉 {symbol} | `{pips}` {unit}"
            elif price >= tp:
                pips = round((tp - entry) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف بنجاح (TP)!** (+{pips} {unit})\n📊 {symbol}"

        elif trade_type == "SELL":
            if price >= sl:
                pips = round((entry - sl) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"❌ **إغلاق: ضرب الستوب (SL)**\n📉 {symbol} | `{pips}` {unit}"
            elif price <= tp:
                pips = round((entry - tp) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف بنجاح (TP)!** (+{pips} {unit})\n📊 {symbol}"

        return None, None

    # مهلة انتظار 15 دقيقة بعد الإغلاق
    cooldown = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown < 15.0:
        return None, None

    bias = get_market_bias(symbol)
    trade_type, trade_data = detect_smc_signal(df_m5, bias)

    if not trade_type:
        return None, None

    sl = trade_data["sl"]
    tp = trade_data["tp"]
    reason = trade_data["reason"]

    current_signal = f"{trade_type}_{round(price, 2)}"
    if current_signal == last_signals[symbol]:
        return None, None

    last_signals[symbol] = current_signal
    entry = price
    active_trades[symbol] = {
        "type": trade_type,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "entry_time": now
    }

    emoji = "🟢 BUY" if trade_type == "BUY" else "🔴 SELL"
    tv_symbol = f"FX:{symbol.replace('/', '')}" if "BTC" not in symbol and "XAU" not in symbol else ("OANDA:XAUUSD" if "XAU" in symbol else "BINANCE:BTCUSDT")

    message = f"""{emoji}

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف (TP 1:2):** `{tp:.2f}`
🛡️ **الستوب (ATR SL 2.2):** `{sl:.2f}`

🔥 **السبب الفني:** `{reason}`

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def main():
    print(f"🚀 تم تشغيل البوت بالنسخة الاحترافية {VERSION}", flush=True)

    update_msg = f"⚙️ **تم تحديث البوت إلى النسخة `{VERSION}` بنجاح.**\n\n- ربط الاتجاه بفريم الساعة H1 Bias لتفادي الدخول المعاكس.\n- ستوب لوز موسع 2.2 ATR لتقليل الضغط.\n- نظام الحظر ومهلة 15 دقيقة بعد إغلاق الصفقة."
    await send_telegram_msg(update_msg)

    while True:
        try:
            for symbol in SYMBOLS:
                status, msg = process_symbol(symbol)
                if msg:
                    await send_telegram_msg(msg)
                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"Loop Error: {e}", flush=True)

        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
