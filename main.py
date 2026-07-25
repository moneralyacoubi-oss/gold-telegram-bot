import asyncio
import random
from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

async def send_signal():
    signal = random.choice(["BUY", "SELL"])
    price = round(random.uniform(3300, 3400), 2)

    message = f"""
📊 Gold Signal

📈 Signal: {signal}
💰 Symbol: XAUUSD
📍 Entry: {price}
🎯 TP: {price + 10 if signal == 'BUY' else price - 10}
🛑 SL: {price - 5 if signal == 'BUY' else price + 5}

⚠️ Demo Signal
"""

    await bot.send_message(chat_id=CHAT_ID, text=message)

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot Started Successfully")

    while True:
        await send_signal()
        await asyncio.sleep(300)  # كل 5 دقائق

if __name__ == "__main__":
    asyncio.run(main())
