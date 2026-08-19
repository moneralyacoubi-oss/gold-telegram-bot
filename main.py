import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, CHAT_ID

VERSION = "v5.1 (No-Repeat Institutional SMC)"

request = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
bot = Bot(token=BOT_TOKEN, request=request)

API_KEYS = [
    "C8229f7582f645b5a6cb09e6e4490002", "ba9b9b464937486f953d12278ffc0c54",
    "3aa16ae3bc7d44f28cbf629508c020bf", "69b9cd8250344066a54be4108225f849",
    "76a7b6f10798424385db93fe18a56e76", "59d7ff4537d846298cc50992950f0082",
    "ff6c85b0a3f14866938d4c43865ce1df", "10cbf9b6f30043eb96e3ad2a89063f5f",
    "d3bf745e06f74947a25b2175df9fe178", "406452df893f4375a2a79d156f5f66d6",
    "ccfdfdefbd434defaaec9d853680065d", "d29ef2928aae41f2b96fcb7ba8b27f3b",
    "ee4ead027117474e8d53a120c8aeb5e5", "1edb7d5da95b446dba1a97faf74803eb",
    "56f1f5c2abea4989853d20a452f2dce9", "Cf02fa8d0b10466496bfae35bc8e61fc",
    "cf6fff5cc5b9481e9b66b0b4557be3e0", "5ab47caa0b614f56ba9815778f0024cb",
    "c365534f82cf41a7a7e72df8fa9c7637", "7b13e064b5f6406e9a98e78777c5ea91",
    "541bef3becfb4d45a7ead575f147d407", "cc82a74ca22c4b8d8f95f9ab7132b8b9",
    "6b3970b4f67d4b68a6e26d2b5357373b", "18d552240c38461da8eb89be259b2250",
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
    return get_now().weekday() not in [5, 6]

def is_active_session():
    return 10 <= get_now().hour < 21

SYMBOLS = ["XAU/USD", "BTC/USD", "EUR/USD", "GBP/USD", "GBP/JPY", "USD/JPY"]

last_signals = {s: None for s in SYMBOLS}

async def send_telegram_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Telegram Error: {e}", flush=True)

def fetch_data(symbol, timeframe, outputsize=50):
    global active_keys
    api_key = get_next_api_key()
    if not api_key: return None
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize={outputsize}&apikey={api_key}"
    try:
        res = requests.get(url, timeout=15).json()
        if "values" in res:
            df = pd.DataFrame(res["values"]).iloc[::-1].reset_index(drop=True)
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)
            return df
    except Exception:
        pass
    return None

def get_market_bias(symbol):
    df_h1 = fetch_data(symbol, "1h", 30)
    if df_h1 is None or len(df_h1) < 20: return "NEUTRAL"
    ema = df_h1['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    price = df_h1['close'].iloc[-1]
    return "BULLISH" if price > ema else "BEARISH"

def calculate_atr(df, period=14):
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    return df[['h-l', 'h-pc', 'l-pc']].max(axis=1).rolling(period).mean().iloc[-1]

def detect_institutional_signal(df_m15, bias):
    if df_m15 is None or len(df_m15) < 20: return None, None
    
    current_price = df_m15['close'].iloc[-1]
    atr = calculate_atr(df_m15)
    
    recent_low = df_m15['low'].iloc[-15:-3].min()
    recent_high = df_m15['high'].iloc[-15:-3].max()
    
    sweep_bull = df_m15['low'].iloc[-2] < recent_low and df_m15['close'].iloc[-2] > recent_low
    fvg_bull = df_m15['low'].iloc[-1] > df_m15['high'].iloc[-3]
    
    if bias == "BULLISH" and (sweep_bull or fvg_bull):
        sl = min(df_m15['low'].iloc[-3:]) - (atr * 0.5)
        risk = current_price - sl
        if risk <= 0: return None, None
        tp = current_price + (risk * 2.0)
        return "BUY", {"sl": sl, "tp": tp, "reason": "Liquidity Sweep + FVG Mitigation"}

    sweep_bear = df_m15['high'].iloc[-2] > recent_high and df_m15['close'].iloc[-2] < recent_high
    fvg_bear = df_m15['high'].iloc[-1] < df_m15['low'].iloc[-3]

    if bias == "BEARISH" and (sweep_bear or fvg_bear):
        sl = max(df_m15['high'].iloc[-3:]) + (atr * 0.5)
        risk = sl - current_price
        if risk <= 0: return None, None
        tp = current_price - (risk * 2.0)
        return "SELL", {"sl": sl, "tp": tp, "reason": "Liquidity Sweep + FVG Mitigation"}

    return None, None

def process_symbol(symbol):
    global last_signals

    if "BTC" not in symbol and (not is_market_open() or not is_active_session()):
        return None, None

    df_m15 = fetch_data(symbol, "15min", 30)
    if df_m15 is None: return None, None

    price = float(df_m15["close"].iloc[-1])
    bias = get_market_bias(symbol)
    trade_type, trade_data = detect_institutional_signal(df_m15, bias)

    if not trade_type: 
        last_signals[symbol] = None
        return None, None

    # منع تكرار نفس الإشارة لنفس الزوج متتالياً
    signal_key = f"{trade_type}_{round(price, 1)}"
    if last_signals[symbol] == signal_key:
        return None, None

    sl, tp, reason = trade_data["sl"], trade_data["tp"], trade_data["reason"]
    last_signals[symbol] = signal_key

    emoji = "🟢 BUY" if trade_type == "BUY" else "🔴 SELL"
    msg = f"{emoji} **إشارة جديدة**"
    msg += f"\n\n📌 **الرمز:** `{symbol}`\n📍 **الدخول:** `{price:.2f}`\n🎯 **الهدف:** `{tp:.2f}`\n🛡️ **الستوب:** `{sl:.2f}`\n🔥 **السبب:** `{reason}`"
    return trade_type, msg

async def main():
    print(f"🚀 تم تشغيل الاستراتيجية {VERSION}", flush=True)
    await send_telegram_msg(f"⚙️ **تم تحديث البوت إلى `{VERSION}` (منع تكرار الإشارات)**")
    while True:
        try:
            for symbol in SYMBOLS:
                status, msg = process_symbol(symbol)
                if msg: 
                    await send_telegram_msg(msg)
                await asyncio.sleep(2)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
