def get_analysis():
    df = yf.download("GC=F", period="2d", interval="5m", progress=False)

    print(df.tail())
    print(df.empty)

    if df.empty:
        return "❌ فشل في جلب بيانات الذهب."

    close = df["Close"]
