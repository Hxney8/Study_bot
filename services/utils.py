from datetime import datetime
from database.db import db
import pytz
import re

# utils
def format_local(dt: datetime, user_tz: pytz.timezone) -> str:
    """Return `YYYY‑MM‑DD HH:MM` in the user’s own timezone."""
    return dt.astimezone(user_tz).strftime('%Y‑%m‑%d %H:%M')

def slugify(text):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)[:50]

async def parse_datetime(date_str: str, time_str: str, user_id: int) -> datetime:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        time_obj = datetime.strptime(time_str, "%H:%M").time()
        user_timezone = await db.get_user_timezone(user_id)
        naive_datetime = datetime.combine(date_obj, time_obj)
        if naive_datetime.tzinfo is None:
            return user_timezone.localize(naive_datetime)
        else:
            return naive_datetime.astimezone(user_timezone)
    except ValueError:
        raise ValueError("Invalid format. Use YYYY-MM-DD for date and HH:MM for time")
    
def create_styled_email(subject: str, content: str) -> str:
    """Generate a styled HTML email with a consistent design."""
    return (
        "<!DOCTYPE html>"
        "<html lang='en'>"
        "<head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        f"<title>{subject}</title>"
        "</head>"
        "<body style='font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #333333; margin: 0; padding: 20px;'>"
        "<div style='max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border: 1px solid #dddddd; border-radius: 5px;'>"
        f"<h2 style='font-size: 18px; color: #444444; margin: 0 0 10px;'>{subject}</h2>"
        f"{content}"
        "</div>"
        "</body>"
        "</html>"
    )
