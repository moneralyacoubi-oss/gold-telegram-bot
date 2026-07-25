def get_analysis():
    url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=5min&outputsize=100&apikey={API_KEY}"

    response = requests.get(url)
    data = response.json()

    print(data)

    if "values" not in data:
        raise Exception(data)

    df = pd.DataFrame(data["values"])
    df["close"] = df["close"].astype(float)
    df = df.iloc[::-1]

    ema20 = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
    ema50 = EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]
    rsi = RSIIndicator(df["close"], window=14).rsi().iloc[-1]
    macd = MACD(df["close"]).macd().iloc[-1]
    signal = MACD(df["close"]).macd_signal().iloc[-1]
    price = df["close"].iloc[-1]

    return f"""📊 Gold Analysis

💰 Price: {price:.2f}
📈 EMA20: {ema20:.2f}
📉 EMA50: {ema50:.2f}
📊 RSI: {rsi:.2f}
📉 MACD: {macd:.3f}
📈 Signal: {signal:.3f}
"""
