import asyncio
from datetime import datetime
import pandas as pd
import pytz
import MetaTrader5 as mt5
from telegram import Bot
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, CHAT_ID

VERSION = "v6.0 (Direct MT5 Feed - Perfect Price Precision)"

request = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
bot = Bot(token=BOT_TOKEN, request=request)

IRAQ_TZ = pytz.timezone("Asia/Baghdad")

def get_now():
    return datetime.now(IRAQ_TZ)

def is_market_open():
    return get_now().weekday() not in [5, 6]

def is_active_session():
    return 10 <= get_now().hour < 21

# الرموز كما هي مكتوبة في منصة MT5 الخاصة بك
SYMBOLS = ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "GBPJPY", "USDJPY"]

active_trades = {s: None for s in SYMBOLS}

def format_price(symbol, price):
    if price is None: return "0.00"
    if "JPY" in symbol:
        return f"{price:.3f}"
    elif "XAU" in symbol or "BTC" in symbol:
        return f"{price:.2f}"
    else:
        return f"{price:.5f}"

async def send_telegram_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Telegram Error: {e}", flush=True)

def fetch_data_from_mt5(symbol, timeframe_mt5, count=50):
    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def get_market_bias(symbol):
    df_h1 = fetch_data_from_mt5(symbol, mt5.TIMEFRAME_H1, 40)
    if df_h1 is None or len(df_h1) < 30: return "NEUTRAL"
    
    if "XAU" in symbol:
        h1_highs = df_h1['high'].rolling(5).max()
        h1_lows = df_h1['low'].rolling(5).min()
        prev_low, curr_low = h1_lows.iloc[-15], h1_lows.iloc[-2]
        prev_high, curr_high = h1_highs.iloc[-15], h1_highs.iloc[-2]
        
        if curr_low > prev_low and curr_high >= prev_high:
            return "BULLISH"
        elif curr_high < prev_high and curr_low <= prev_low:
            return "BEARISH"
        return "NEUTRAL"

    ema = df_h1['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    price = df_h1['close'].iloc[-1]
    return "BULLISH" if price > ema else "BEARISH"

def detect_institutional_signal(symbol, df_m15, bias):
    if df_m15 is None or len(df_m15) < 20 or bias == "NEUTRAL": 
        return None, None
    
    current_price = df_m15['close'].iloc[-1]

    recent_low = df_m15['low'].iloc[-8:-2].min()
    recent_high = df_m15['high'].iloc[-8:-2].max()
    
    sweep_bull = df_m15['low'].iloc[-2] < recent_low and df_m15['close'].iloc[-2] > recent_low
    fvg_bull = df_m15['low'].iloc[-1] > df_m15['high'].iloc[-3]
    
    if bias == "BULLISH" and (sweep_bull or fvg_bull):
        sl = df_m15['low'].iloc[-2]
        risk = current_price - sl
        if risk <= 0: return None, None
        
        tp1 = current_price + (risk * 1.2)
        tp2 = current_price + (risk * 2.0)
        tp3 = current_price + (risk * 2.8)
        return "BUY", {"sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3}

    sweep_bear = df_m15['high'].iloc[-2] > recent_high and df_m15['close'].iloc[-2] < recent_high
    fvg_bear = df_m15['high'].iloc[-1] < df_m15['low'].iloc[-3]

    if bias == "BEARISH" and (sweep_bear or fvg_bear):
        sl = df_m15['high'].iloc[-2]
        risk = sl - current_price
        if risk <= 0: return None, None
        
        tp1 = current_price - (risk * 1.2)
        tp2 = current_price - (risk * 2.0)
        tp3 = current_price - (risk * 2.8)
        return "SELL", {"sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3}

    return None, None

async def process_symbol(symbol):
    global active_trades

    if "BTC" not in symbol and (not is_market_open() or not is_active_session()):
        return

    df_m15 = fetch_data_from_mt5(symbol, mt5.TIMEFRAME_M15, 30)
    if df_m15 is None: return

    current_price = float(df_m15["close"].iloc[-1])
    high_price = float(df_m15["high"].iloc[-1])
    low_price = float(df_m15["low"].iloc[-1])

    if active_trades[symbol] is not None:
        trade = active_trades[symbol]
        
        if trade["type"] == "BUY":
            if high_price >= trade["tp3"]:
                await send_telegram_msg(f"🎯 **تم تحقيق جميع الأهداف (TP3)!**\n📌 **الرمز:** `{symbol}`\n💰 **عند:** `{format_price(symbol, trade['tp3'])}`")
                active_trades[symbol] = None
            elif low_price <= trade["sl"]:
                await send_telegram_msg(f"🛡️ **تم ضرب الستوب (SL)!**\n📌 **الرمز:** `{symbol}`\n🔻 **عند:** `{format_price(symbol, trade['sl'])}`")
                active_trades[symbol] = None
                
        elif trade["type"] == "SELL":
            if low_price <= trade["tp3"]:
                await send_telegram_msg(f"🎯 **تم تحقيق جميع الأهداف (TP3)!**\n📌 **الرمز:** `{symbol}`\n💰 **عند:** `{format_price(symbol, trade['tp3'])}`")
                active_trades[symbol] = None
            elif high_price >= trade["sl"]:
                await send_telegram_msg(f"🛡️ **تم ضرب الستوب (SL)!**\n📌 **الرمز:** `{symbol}`\n🔻 **عند:** `{format_price(symbol, trade['sl'])}`")
                active_trades[symbol] = None

        return

    bias = get_market_bias(symbol)
    trade_type, trade_data = detect_institutional_signal(symbol, df_m15, bias)

    if trade_type:
        sl, tp1, tp2, tp3 = trade_data["sl"], trade_data["tp1"], trade_data["tp2"], trade_data["tp3"]
        
        active_trades[symbol] = {
            "type": trade_type,
            "entry": current_price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3
        }

        emoji = "🟢 BUY" if trade_type == "BUY" else "🔴 SELL"
        msg = f"{emoji} `{symbol}`\n\n"
        msg += f"📍 **سعر الدخول:** `{format_price(symbol, current_price)}`\n"
        msg += f"🎯 **TP1:** `{format_price(symbol, tp1)}`\n"
        msg += f"🎯 **TP2:** `{format_price(symbol, tp2)}`\n"
        msg += f"🎯 **TP3:** `{format_price(symbol, tp3)}`\n"
        msg += f"🛡️ **SL:** `{format_price(symbol, sl)}`"
        
        await send_telegram_msg(msg)

async def main():
    if not mt5.initialize():
        print("❌ فشل الاتصال بـ MetaTrader 5! تأكد من فتح البرنامج على الحاسبة.")
        return
    
    print(f"🚀 تم تشغيل الاستراتيجية {VERSION}", flush=True)
    await send_telegram_msg(f"⚙️ **تم التحديث إلى `{VERSION}` (ربط مباشر مع MT5)**")
    
    while True:
        try:
            for symbol in SYMBOLS:
                await process_symbol(symbol)
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
