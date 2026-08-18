import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, CHAT_ID

VERSION = "v5.0 (Institutional SMC & Liquidity Sweep)"

request = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
bot = Bot(token=BOT_TOKEN, request=request)

API_KEYS = [
    "C8229f7582f645b5a6cb09e6e4490002", "ba9b9b464937486f953d12278ffc0c54",
    "3aa16ae3bc7d44f28cbf629508c020bf", "69b9cd8250344066a54be4108225f849",
    "76a7b6f10798424385db93fe18a56e76", "59d7ff4537d846298cc50992950f0082",
    "ff6c85b0a3f14866938d4c43865ce1df", "10cbf9b6f30043eb96e3ad2a89063f5f",
    "d3bf745e06f74947a25b2175df9fe178", "406452df893f4375a2a79d156f5f66d6"
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
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: datetime.min.replace(tzinfo=IRAQ_TZ) for s in SYMBOLS}

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
    
    # شرط الشراء: سحب سيولة للقاع السابق واختراق تعافٍ مع الاتجاه
    sweep_bull = df_m15['low'].iloc[-2] < recent_low and df_m15['close'].iloc[-2] > recent_low
    fvg_bull = df_m15['low'].iloc[-1] > df_m15['high'].iloc[-3]
    
    if bias == "BULLISH" and (sweep_bull or fvg_bull):
        sl = min(df_m15['low'].iloc[-3:]) - (atr * 0.5)
        risk = current_price - sl
        if risk <= 0: return None, None
        tp = current_price + (risk * 2.0)
        return "BUY", {"sl": sl, "tp": tp, "reason": "Liquidity Sweep + FVG Mitigation"}

    # شرط البيع: سحب سيولة للقمة السابقة واختراق تعافٍ مع الاتجاه
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
    now = get_now()
    if "BTC" not in symbol and (not is_market_open() or not is_active_session()):
        return None, None

    df_m15 = fetch_data(symbol, "15min", 30)
    if df_m15 is None: return None, None

    price = float(df_m15["close"].iloc[-1])
    bias = get_market_bias(symbol)
    trade_type, trade_data = detect_institutional_signal(df_m15, bias)

    if not trade_type: return None, None

    sl, tp, reason = trade_data["sl"], trade_data["tp"], trade_data["reason"]
    
    msg = f"🟢 **إشارة شراء جديدة**" if trade_type == "BUY" else f"🔴 **إشارة بيع جديدة**"
    msg += f"\n\n📌 **الرمز:** `{symbol}`\n📍 **الدخول:** `{price:.2f}`\n🎯 **الهدف:** `{tp:.2f}`\n🛡️ **الستوب:** `{sl:.2f}`\n🔥 **السبب:** `{reason}`"
    return trade_type, msg

async def main():
    await send_telegram_msg(f"🚀 **تم تشغيل الاستراتيجية المؤسسية `{VERSION}`**")
    while True:
        try:
            for symbol in SYMBOLS:
                status, msg = process_symbol(symbol)
                if msg: await send_telegram_msg(msg)
                await asyncio.sleep(2)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
