async def main():
    await bot.send_message(
        chat_id=CHAT_ID,
        text="✅ Gold Analysis Bot Started"
    )

    while True:
        try:
            analysis = get_analysis()

            # لا ترسل الإشارات الضعيفة
            if analysis and "🟡 WAIT" not in analysis and "قوة الإشارة: 70%" in analysis or "قوة الإشارة: 80%" in analysis or "قوة الإشارة: 85%" in analysis or "قوة الإشارة: 100%" in analysis:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=analysis
                )

        except Exception as e:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"❌ Error:\n{e}"
            )

        await asyncio.sleep(300)
