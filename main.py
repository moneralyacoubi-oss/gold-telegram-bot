# main.py
import asyncio
from datetime import datetime
import requests
import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID, API_KEY

bot = Bot(token=BOT_TOKEN)

def get_analysis():
    try:
        url=f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=5min&outputsize=100&apikey={API_KEY}"
        data=requests.get(url,timeout=10).json()
        if "values" not in data:
            return f"❌ API Error:\n{data}"
        df=pd.DataFrame(data["values"]).iloc[::-1]
        for c in ["open","high","low","close"]:
            df[c]=df[c].astype(float)
        close=df["close"]; high=df["high"]; low=df["low"]
        ema20=EMAIndicator(close,20).ema_indicator().iloc[-1]
        ema50=EMAIndicator(close,50).ema_indicator().iloc[-1]
        rsi=RSIIndicator(close,14).rsi().iloc[-1]
        m=MACD(close)
        macd=m.macd().iloc[-1]
        sig=m.macd_signal().iloc[-1]
        price=close.iloc[-1]
        support=low.tail(20).min()
        resistance=high.tail(20).max()
        strength=0
        trend="🟢 صاعد" if ema20>ema50 else "🔴 هابط"
        if ema20>ema50: strength+=40
        macd_txt="🟢 إيجابي" if macd>sig else "🔴 سلبي"
        if macd>sig: strength+=30
        if rsi<30:
            rsi_txt="🟢 تشبع بيعي"; strength+=30
        elif rsi>70:
            rsi_txt="🔴 تشبع شرائي"
        else:
            rsi_txt="🟡 طبيعي"; strength+=15
        signal="🟢 BUY" if strength>=70 else ("🔴 SELL" if strength<=30 else "🟡 WAIT")
        return f"""📊 GOLD ANALYSIS

💰 السعر: {price:.2f}
📈 الاتجاه: {trend}
📊 RSI: {rsi:.2f} - {rsi_txt}
📉 MACD: {macd_txt}
🟢 الدعم: {support:.2f}
🔴 المقاومة: {resistance:.2f}
🎯 قوة الإشارة: {strength}%
📌 القرار: {signal}
🕒 الفريم: M5
⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    except Exception as e:
        return f"❌ Error:\n{e}"

async def main():
    await bot.send_message(chat_id=CHAT_ID,text="✅ Gold Bot Started")
    while True:
        await bot.send_message(chat_id=CHAT_ID,text=get_analysis())
        await asyncio.sleep(300)

if __name__=="__main__":
    asyncio.run(main())
