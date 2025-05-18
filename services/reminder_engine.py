from datetime import datetime
import traceback

from loader import bot, logger
from services.email_service import send_email
from services.utils import create_styled_email
from database.db import db


async def remind_event(user_id: int, event: str, when_local: str):
    """One-off reminder for a scheduled event."""
    event = sanitize(event)
    when_local = sanitize(when_local)

    plain_text = f"Schedule Reminder\n\nEvent: {event}\nTime: {when_local}"
    html_content = (
        "<p style='margin: 0 0 10px;'>⏰ <strong>Upcoming Event</strong></p>"
        f"<p style='margin: 0 0 5px;'>Event: {event}</p>"
        f"<p style='margin: 0 0 5px;'>Time: {when_local}</p>"
    )
    html_body = create_styled_email(f"Upcoming event: {event}", html_content)

    await bot.send_message(user_id, f"⏰ Schedule Reminder:\n“{event}”\nis on {when_local}")
    await _maybe_send_email(user_id, f"Upcoming event: {event}", html_body, plain_text=plain_text)


async def remind_task(user_id: int, task: str, when_local: datetime):
    """Task reminder (when_local already in user’s TZ)."""
    task = sanitize(task)
    pretty = sanitize(when_local.strftime("%Y-%m-%d %H:%M"))

    plain_text = f"Task Reminder\n\nTask: {task}\nDue: {pretty}"
    html_content = (
        "<p style='margin: 0 0 10px;'>📝 <strong>Task Due</strong></p>"
        f"<p style='margin: 0 0 5px;'>Task: {task}</p>"
        f"<p style='margin: 0 0 5px;'>Due: {pretty}</p>"
    )
    html_body = create_styled_email(f"Task due: {task}", html_content)

    await bot.send_message(user_id, f"📝 Task Reminder:\n“{task}”\nis due on {pretty}")
    await _maybe_send_email(user_id, f"Task due: {task}", html_body, plain_text=plain_text)


async def send_task_reminder(user_id, task, deadline, category):
    """Simple reminder message for a task (no email)."""
    try:
        await bot.send_message(user_id, f"🔔 Reminder: {task} ({category}) is due on {deadline}!")
        logger.info(f"Sent task reminder to user {user_id} for {task}")
    except Exception as e:
        logger.error(f"Error sending task reminder to user {user_id}: {str(e)}")


async def _maybe_send_email(user_id: int, subject: str, body: str, content_type: str = "text/html", plain_text: str = None):
    """Conditionally sends an email if user has email enabled + configured."""
    try:
        email, enabled = await db.get_email_prefs(user_id)
        if enabled and email:
            await send_email(
                to_addr=email,
                subject=subject,
                body=body,
                content_type=content_type,
                plain_text=plain_text
            )
        else:
            logger.info("Email not sent to user %s (disabled or missing address)", user_id)
    except Exception as e:
        logger.error("Email to user %s failed: %s\n%s", user_id, e, traceback.format_exc())


def sanitize(text: str) -> str:
    """Basic HTML sanitizer for Telegram messages."""
    return text.replace('<', '&lt;').replace('>', '&gt;')
