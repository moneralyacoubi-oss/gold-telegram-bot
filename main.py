from telegram import Bot
from config import BOT_TOKEN, CHAT_ID

bot = Bot(token=BOT_TOKEN)

async def main():
    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Moner Gold Signal Bot is now running!"
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())