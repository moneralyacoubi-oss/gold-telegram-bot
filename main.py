# قاموس لتخزين مناطق H1 وتقليل استهلاك الـ API
poi_cache = {}
last_h1_fetch = {s: datetime.min.replace(tzinfo=IRAQ_TZ) for s in SYMBOLS}

def process_symbol(symbol):
    global last_signals, active_trades, last_trade_closed_times, poi_cache, last_h1_fetch

    now = get_now()
    
    # جلب بيانات H1 مرة واحدة كل 30 دقيقة فقط لتوفير الـ API
    if symbol not in poi_cache or (now - last_h1_fetch[symbol]).total_seconds() > 1800:
        df_h1 = fetch_data(symbol, "1h", 60)
        if df_h1 is not None:
            poi_demand, poi_supply = find_poi_zones(df_h1)
            poi_cache[symbol] = (poi_demand, poi_supply, df_h1)
            last_h1_fetch[symbol] = now

    if symbol not in poi_cache:
        return None, None

    poi_demand, poi_supply, df_h1 = poi_cache[symbol]
    
    # جلب فريم M5 السريع فقط في كل دورة
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

    emoji = "🟢 BUY (منطقة سيولة عالية الدقة)" if trade_type == "BUY" else "🔴 SELL (منطقة سيولة عالية الدقة)"
    tv_symbol = f"FX:{symbol.replace('/', '')}" if "BTC" not in symbol and "XAU" not in symbol else ("OANDA:XAUUSD" if "XAU" in symbol else "BINANCE:BTCUSDT")

    message = f"""{emoji}

📌 **الرمز:** `{symbol}`
📍 **سعر الدخول:** `{entry:.2f}`

🎯 **الهدف (TP):** `{tp:.2f}`
🛡️ **الستوب (SL):** `{sl:.2f}`

✨ *توافق الاتجاه العام H1 مع منطقة POI حقيقية.*

📈 [فتح الشارت على TradingView](https://www.tradingview.com/chart/?symbol={tv_symbol})
"""
    return "NEW_TRADE", message
