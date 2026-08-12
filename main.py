import asyncio
from datetime import datetime
import requests
import pandas as pd
import pytz
from telegram import Bot

from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

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

# إضافة أزواج سريعة ومتحركة لزيادة الصفقات اليومية
SYMBOLS = ["XAU/USD", "GBP/USD", "BTC/USD", "EUR/USD", "GBP/JPY"]

last_signals = {s: None for s in SYMBOLS}
active_trades = {s: None for s in SYMBOLS}
last_trade_closed_times = {s: datetime.min.replace(tzinfo=IRAQ_TZ) for s in SYMBOLS}

def fetch_data(symbol, timeframe, outputsize=100):
    api_key = get_next_api_key()
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize={outputsize}&apikey={api_key}"
    try:
        res = requests.get(url, timeout=8).json()
        if "values" not in res:
            return None
        df = pd.DataFrame(res["values"]).iloc[::-1].reset_index(drop=True)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"API Fetch Error ({symbol}): {e}")
        return None

def calculate_ema(df, period=30):
    """EMA30 على M15 لتحديد الاتجاه اللحظي السريع"""
    return df['close'].ewm(span=period, adjust=False).mean().iloc[-1]

def find_poi_zones_fast(df_m15):
    """استخراج مناطق POI سريعة من فريم المربعات M15"""
    if df_m15 is None or len(df_m15) < 12:
        return None, None
    
    lows = df_m15['low'].tail(12)
    highs = df_m15['high'].tail(12)
    
    poi_demand = {"low": lows.min(), "high": lows.min() + (df_m15['high'].iloc[-1] - df_m15['low'].iloc[-1]) * 0.3}
    poi_supply = {"high": highs.max(), "low": highs.max() - (df_m15['high'].iloc[-1] - df_m15['low'].iloc[-1]) * 0.3}
    
    return poi_demand, poi_supply

def detect_fast_accurate_signal(df_m5, df_m15, poi_demand, poi_supply):
    """فحص الصفقات السريعة بتأكيد قوي مع الاتجاه"""
    if df_m5 is None or len(df_m5) < 3 or df_m15 is None:
        return None, None

    ema30_m15 = calculate_ema(df_m15, 30)
    current_price = df_m5['close'].iloc[-1]
    last_low = df_m5['low'].iloc[-1]
    last_high = df_m5['high'].iloc[-1]
    
    # تأكيد شمعة انعكاسية بسيطة
    is_bullish = df_m5['close'].iloc[-1] > df_m5['open'].iloc[-1]
    is_bearish = df_m5['close'].iloc[-1] < df_m5['open'].iloc[-1]

    # صفقة شراء سريعة
    if poi_demand and poi_demand["low"] <= last_low <= poi_demand["high"]:
        if current_price >= ema30_m15 and is_bullish:
            sl = poi_demand["low"] - (poi_demand["high"] - poi_demand["low"]) * 0.15
            risk = current_price - sl
            if risk <= 0: return None, None
            tp = current_price + (risk * 1.3)  # هدف سريع وخاطف لضمان التحقق
            return "BUY", {"sl": sl, "tp": tp}

    # صفقة بيع سريعة
    if poi_supply and poi_supply["low"] <= last_high <= poi_supply["high"]:
        if current_price <= ema30_m15 and is_bearish:
            sl = poi_supply["high"] + (poi_supply["high"] - poi_supply["low"]) * 0.15
            risk = sl - current_price
            if risk <= 0: return None, None
            tp = current_price - (risk * 1.3)  # هدف سريع وخاطف لضمان التحقق
            return "SELL", {"sl": sl, "tp": tp}

    return None, None

def get_pip_multiplier(symbol):
    if "BTC" in symbol: return 1.0
    elif "XAU" in symbol: return 10.0
    else: return 10000.0

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_closed_times

    df_m15 = fetch_data(symbol, "15min", 40)
    df_m5 = fetch_data(symbol, "5min", 30)

    if df_m15 is None or df_m5 is None:
        return None, None

    price = float(df_m5["close"].iloc[-1])
    now = get_now()
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

    # تبريد دقيقة واحدة فقط لإفساح المجال لفرص يومية متكررة
    cooldown = (now - last_trade_closed_times[symbol]).total_seconds() / 60.0
    if cooldown < 1.0:
        return None, None

    poi_demand, poi_supply = find_poi_zones_fast(df_m15)
    trade_type, trade_data = detect_fast_accurate_signal(df_m5, df_m15, poi_demand, poi_supply)

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

    emoji = "🟢 BUY (سكالبينج يومي سريع)" if trade_type == "BUY" else "🔴 SELL (سكالبينج يومي سريع)"
    tv_symbol = f"FX:{symbol.replace('/', '')}" if "BTC" not in symbol and "XAU" not in symbol else ("OANDA:XAUUSD" if "XAU" in symbol else "BINANCE:BTCUSDT")

    message = f"""{emoji}

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف السريع (TP):** `{tp:.2f}`
🛡️ **الستوب (SL):** `{sl:.2f}`

⚡ *تأكيد سريع على M15 لتحقيق أهداف يومية مضمونة.*

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message

async def main():
    print("🚀 جاري تشغيل نسخة السكالبينج اليومية السريعة V5.5...", flush=True)

    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="⚡ **تم تحديث البوت إلى النسخة V5.5 (سريع ومضمون اليوم):**\n1. التحويل لفريم M15 لزيادة الصفقات اليومية.\n2. تقليل الأهداف (RR 1:1.3) لضمان تحقيق الـ TP بسرعة.\n3. تبريد دقيقة واحدة لخلق فرص مستمرة.",
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
                await asyncio.sleep(1)

        except Exception as e:
            print(f"Loop Error: {e}", flush=True)

        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
