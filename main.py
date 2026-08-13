import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

# مفاتيح API لتدوير الاستهلاك
API_KEYS = [
    "cf02fa8d0b10466496bfae35bc8e61fc", "cf6fff5cc5b9481e9b66b0b4557be3e0", 
    "5ab47caa0b614f56ba9815778f0024cb", "c365534f82cf41a7a7e72df8fa9c7637", 
    "7b13e064b5f6406e9a98e78777c5ea91", "541bef3becfb4d45a7ead575f147d407", 
    "cc82a74ca22c4b8d8f95f9ab7132b8b9", "6b3970b4f67d4b68a6e26d2b5357373b", 
    "18d552240c38461da8eb89be259b2250", "7d34370b5fbf4160a6b04f07ede97648"
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

SYMBOLS = [
    "XAU/USD", "BTC/USD", "EUR/USD", "GBP/USD", 
    "GBP/JPY", "EUR/JPY", "AUD/USD", "USD/JPY"
]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: datetime.min.replace(tzinfo=IRAQ_TZ) for s in SYMBOLS}

poi_cache = {}
last_h1_fetch = {s: datetime.min.replace(tzinfo=IRAQ_TZ) for s in SYMBOLS}

def fetch_data(symbol, timeframe, outputsize=80, retries=3):
    """جلب البيانات مع نظام المحاولات وزيادة المهلة لحل مشكلة Timeout"""
    for attempt in range(retries):
        api_key = get_next_api_key()
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize={outputsize}&apikey={api_key}"
        try:
            # رفع مهلة الانتظار إلى 15 ثانية لتفادي انقطاع الاتصال
            res = requests.get(url, timeout=15).json()
            if "values" in res:
                df = pd.DataFrame(res["values"]).iloc[::-1].reset_index(drop=True)
                for col in ["open", "high", "low", "close"]:
                    df[col] = df[col].astype(float)
                return df
            elif "message" in res:
                print(f"API Warning ({symbol}): {res['message']}", flush=True)
        except Exception as e:
            print(f"API Fetch Retry {attempt + 1}/{retries} ({symbol}): {e}", flush=True)
            
    return None

def calculate_ema(df, period=50):
    return df['close'].ewm(span=period, adjust=False).mean().iloc[-1]

def find_poi_zones(df_h1):
    if df_h1 is None or len(df_h1) < 20:
        return None, None
    
    lows = df_h1['low'].tail(20)
    highs = df_h1['high'].tail(20)
    
    range_span = highs.max() - lows.min()
    
    poi_demand = {"low": lows.min(), "high": lows.min() + (range_span * 0.18)}
    poi_supply = {"high": highs.max(), "low": highs.max() - (range_span * 0.18)}
    
    return poi_demand, poi_supply

def detect_high_precision_signal(df_m5, df_h1, poi_demand, poi_supply):
    if df_m5 is None or len(df_m5) < 5 or df_h1 is None:
        return None, None

    ema50_h1 = calculate_ema(df_h1, 50)
    current_price = df_m5['close'].iloc[-1]
    last_low = df_m5['low'].iloc[-1]
    last_high = df_m5['high'].iloc[-1]

    if poi_demand and (last_low <= poi_demand["high"] and current_price >= poi_demand["low"]):
        if current_price > (ema50_h1 * 0.998):
            sl = poi_demand["low"] - (poi_demand["high"] - poi_demand["low"]) * 0.2
            risk = current_price - sl
            if risk <= 0: return None, None
            tp = current_price + (risk * 1.5)
            return "BUY", {"sl": sl, "tp": tp}

    if poi_supply and (last_high >= poi_supply["low"] and current_price <= poi_supply["high"]):
        if current_price < (ema50_h1 * 1.002):
            sl = poi_supply["high"] + (poi_supply["high"] - poi_supply["low"]) * 0.2
            risk = sl - current_price
            if risk <= 0: return None, None
            tp = current_price - (risk * 1.5)
            return "SELL", {"sl": sl, "tp": tp}

    return None, None

def get_pip_multiplier(symbol):
    if "BTC" in symbol: return 1.0
    elif "XAU" in symbol: return 10.0
    elif "JPY" in symbol: return 100.0
    else: return 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_closed_times, poi_cache, last_h1_fetch

    now = get_now()

    if symbol not in poi_cache or (now - last_h1_fetch[symbol]).total_seconds() > 1800:
        df_h1 = fetch_data(symbol, "1h", 60)
        if df_h1 is not None:
            poi_demand, poi_supply = find_poi_zones(df_h1)
            poi_cache[symbol] = (poi_demand, poi_supply, df_h1)
            last_h1_fetch[symbol] = now

    if symbol not in poi_cache:
        return None, None

    poi_demand, poi_supply, df_h1 = poi_cache[symbol]

    df_m5 = fetch_data(symbol, "5min", 30)
    if df_m5 is None:
        return None, None

    price = float(df_m5["close"].iloc[-1])
    pip_mult = get_pip_multiplier(symbol)

    active_trade = active_trades[symbol]

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
                return "UPDATE", f"❌ **إغلاق ضرب الستوب (SL)**\n📉 {symbol} | `{pips}` {unit}"
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
                return "UPDATE", f"❌ **إغلاق ضرب الستوب (SL)**\n📉 {symbol} | `{pips}` {unit}"
            elif price <= tp:
                pips = round((entry - tp) * pip_mult, 1)
                active_trades[symbol] = None
                last_trade_closed_times[symbol] = now
                unit = "USD" if "BTC" in symbol else "Pip"
                return "UPDATE", f"🎯 **تحقق الهدف بنجاح (TP)!** (+{pips} {unit})\n📊 {symbol}"

        return None, None

    cooldown = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown < 3.0:
        return None, None

    trade_type, trade_data = detect_high_precision_signal(df_m5, df_h1, poi_demand, poi_supply)

    if not trade_type:
        return None, None

    sl = trade_data["sl"]
    tp = trade_data["tp"]

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

    emoji = "🟢 BUY (منطقة سيولة POI)" if trade_type == "BUY" else "🔴 SELL (منطقة سيولة POI)"
    tv_symbol = f"FX:{symbol.replace('/', '')}" if "BTC" not in symbol and "XAU" not in symbol else ("OANDA:XAUUSD" if "XAU" in symbol else "BINANCE:BTCUSDT")

    message = f"""{emoji}

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف (TP):** `{tp:.2f}`
🛡️ **الستوب (SL):** `{sl:.2f}`

✨ *توافق الاتجاه العام H1 مع منطقة POI.*

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def main():
    print("🚀 جاري تشغيل النسخة المستقرة لمعالجة المهلة...", flush=True)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="⚙️ **تم إصلاح مشكلة المهلة (Timeout) والسكربت شغال بانتظام الآن.**",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Telegram Test Error: {e}", flush=True)

    loop_count = 0

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
                # مهلة ثانية واحدة لمنع ازدحام الطلبات على Railway
                await asyncio.sleep(1.0)

            loop_count += 1
            if loop_count >= 150:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text="📡 **السكربت شغال ويراقب الأزواج الثمانية بنجاح.**",
                    parse_mode="Markdown"
                )
                loop_count = 0

        except Exception as e:
            print(f"Loop Error: {e}", flush=True)

        await asyncio.sleep(4)

if __name__ == "__main__":
    asyncio.run(main())
