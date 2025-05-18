# handlers/timezone.py
import difflib
from datetime import datetime

import pytz
from aiogram import types
from aiogram.dispatcher import FSMContext

from loader import dp, logger
from database.db import db
from states.forms import SetTimezoneForm
from keyboards.common import main_menu


# ───────────────── ENTRY POINT ──────────────────
async def handle_timezone_menu(message: types.Message, state: FSMContext):
    """
    Opens the timezone wizard: shows current tz + current time and
    switches FSM to SetTimezoneForm.timezone.
    """
    user_id = message.from_user.id

    # 1) Fetch saved value (string _or_ pytz object) or fall back to UTC
    stored_tz = await db.get_user_timezone(user_id) or "UTC"
    if not isinstance(stored_tz, str):
        stored_tz = stored_tz.zone          # convert tz object ➜ canonical name

    # 2) Build tz object and current time display
    user_tz = pytz.timezone(stored_tz)
    now_local = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M")

    # 3) Ask for new tz
    await SetTimezoneForm.timezone.set()
    await message.answer(
        f"📍 Current timezone: <code>{user_tz.zone}</code>\n"
        f"🕒 Current time: {now_local}\n\n"
        "🌐 Enter your new timezone (e.g. <code>Asia/Tashkent</code>, "
        "<code>Europe/London</code>) or press /cancel.\n\n"
        "Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
        parse_mode="HTML",
    )
    logger.info("User %s opened the timezone menu", user_id)


# ──────────────── FSM STATE HANDLER ──────────────
@dp.message_handler(state=SetTimezoneForm.timezone)
async def process_timezone_input(message: types.Message, state: FSMContext):
    """
    Validates user input; if invalid, suggests close matches; if valid, saves.
    """
    user_id = message.from_user.id
    tz_str = message.text.strip()

    # Fast validation
    if tz_str not in pytz.all_timezones:
        # Suggest up to 3 close matches
        matches = difflib.get_close_matches(tz_str, pytz.all_timezones, n=3, cutoff=0.6)
        suggestions = (
            "\n".join(f"• <code>{m}</code>" for m in matches)
            if matches else "No similar timezones found."
        )

        await message.reply(
            f"❌ <b>Invalid timezone</b>: <code>{tz_str}</code>\n\n"
            f"🔍 Did you mean:\n{suggestions}\n\n"
            "Try again or /cancel.",
            parse_mode="HTML",
        )
        logger.warning("User %s entered invalid tz '%s'", user_id, tz_str)
        return

    # Save canonical form
    canonical = pytz.timezone(tz_str).zone
    try:
        await db.set_user_timezone(user_id, canonical)
        await message.reply(
            f"✅ Timezone updated to <code>{canonical}</code>",
            parse_mode="HTML",
            reply_markup=main_menu,
        )
        logger.info("User %s set timezone to %s", user_id, canonical)
    except Exception as exc:
        logger.exception("DB error while setting tz for %s: %s", user_id, exc)
        await message.reply("⚠️ Error saving timezone. Try again later or /cancel.")
    finally:
        await state.finish()


# ────────────────── CANCEL CMD ───────────────────
@dp.message_handler(commands=["cancel"], state=SetTimezoneForm.timezone)
async def cancel_timezone_setting(message: types.Message, state: FSMContext):
    await message.reply("❎ Timezone change cancelled.", reply_markup=main_menu)
    await state.finish()
