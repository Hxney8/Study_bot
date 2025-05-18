import os
import asyncio
from aiogram.utils import executor
from apscheduler.triggers.interval import IntervalTrigger

from config import WEBHOOK_PATH
from database.db import db
from services.scheduler import schedule_reminders, send_due_reminders
from loader import bot, dp, logger, scheduler

# ─── Import all handlers to register them ─────────────────────────────────────
from handlers import (
    common,
    reminders,
    email,
    tasks,
    timezone,
    schedule,
    grades,
    tickets,
    materials,
    file_converter,
    subjects_teachers
)

# ─── Startup routine ──────────────────────────────────────────────────────────
async def on_startup(dp):
    logger.info("Initializing database...")
    await db.init_db()
    await db._ensure_trgm()

    logger.info("Pre-scheduling reminders for future tasks/events...")
    await schedule_reminders()

    logger.info("Scheduling periodic reminders...")
    scheduler.add_job(send_due_reminders, IntervalTrigger(minutes=1))
    scheduler.start()

    webhook_host = os.getenv('WEBHOOK_HOST')
    webhook_url = f"{webhook_host}{WEBHOOK_PATH}"
    logger.info(f"Setting webhook: {webhook_url}")
    await bot.set_webhook(webhook_url)


# ─── Shutdown routine ─────────────────────────────────────────────────────────
async def on_shutdown(dp):
    logger.info("Shutting down...")
    try:
        await bot.delete_webhook()
        logger.info("Webhook deleted")
        await dp.storage.close()
        await dp.storage.wait_closed()
        logger.info("Storage closed")
        scheduler.shutdown()
        logger.info("Scheduler stopped")
        await db.close_pool()
        logger.info("Database pool closed")
        await bot.session.close()
        logger.info("Bot session closed")

        # Cancel any pending asyncio tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("All tasks stopped")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")
    finally:
        logger.info("Bot stopped!")


# ─── Main entry ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if os.getenv('WEBHOOK_HOST'):
        executor.start_webhook(
            dispatcher=dp,
            webhook_path=WEBHOOK_PATH,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            host="0.0.0.0",
            port=8080,
            ssl_context=None  # Handled by NGINX
        )
    else:
        logger.info("WEBHOOK_HOST not set, falling back to polling")
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown
        )
