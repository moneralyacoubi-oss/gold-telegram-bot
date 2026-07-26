def get_analysis():
    df = yf.download("GC=F", period="2d", interval="5m", progress=False)

    if df.empty:
        return "❌ فشل في جلب بيانات الذهب."

    close = df["Close"]

    # إصلاح مشكلة ndarray
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.astype(float)

    ema20 = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(close, window=14).rsi().iloc[-1]

    macd_obj = MACD(close)
    macd = macd_obj.macd().iloc[-1]
    signal = macd_obj.macd_signal().iloc[-1]

    price = float(close.iloc[-1])

    if ema20 > ema50 and macd > signal and rsi < 70:
        recommendation = "🟢 BUY"
    elif ema20 < ema50 and macd < signal and rsi > 30:
        recommendation = "🔴 SELL"
    else:
        recommendation = "🟡 WAIT"

    return f"""📊 Gold Analysis

💰 Price: {price:.2f}

📈 EMA20: {ema20:.2f}
📉 EMA50: {ema50:.2f}
📊 RSI: {rsi:.2f}
📈 MACD: {macd:.3f}

🔥 Recommendation: {recommendation}

⚠️ للتحليل فقط وليس توصية استثمارية.
"""
