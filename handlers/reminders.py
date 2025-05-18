from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.dispatcher.filters.state import State, StatesGroup
from datetime import datetime as dt, timedelta
import pytz

from states.forms import ReminderForm, EmailForm
from loader import bot, dp
from database.db import db


@dp.callback_query_handler(lambda c: c.data == "toggle_daily_reminder")
async def toggle_daily_reminder(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_reminder_settings(user_id)
    new_val = not settings['daily_reminder_enabled']
    await db.update_reminder_setting(user_id, "daily_reminder_enabled", new_val)
    await callback_query.answer("Daily reminder toggled.")
    await send_reminder_menu(callback_query.message, user_id)

@dp.callback_query_handler(lambda c: c.data == "set_pre_event_offset")
async def ask_pre_event_offset(callback_query: types.CallbackQuery):
    await ReminderForm.waiting_offset.set()
    await callback_query.message.answer("⏱ Enter how many minutes before events you want to be reminded (e.g., 60, 120):")
    await callback_query.answer()

@dp.message_handler(state=ReminderForm.waiting_offset)
async def set_pre_event_offset(message: types.Message, state: FSMContext):
    try:
        val = int(message.text.strip())
        if val < 5 or val > 1440:
            raise ValueError
        await db.update_reminder_setting(message.from_user.id, "pre_event_offset_minutes", val)
        await message.reply(f"Reminder offset set to {val} minutes.")
    except ValueError:
        await message.reply("❌ Please enter a valid number between 5 and 1440.")
        return
    await state.finish()
    await send_reminder_menu(message, message.from_user.id)

@dp.callback_query_handler(lambda c: c.data == "set_daily_reminder_time")
async def ask_daily_reminder_time(callback_query: types.CallbackQuery):
    await ReminderForm.waiting_daily_time.set()
    await callback_query.message.answer("🕒 Enter new daily reminder time (e.g., 08:00 or 18:30):")
    await callback_query.answer()

@dp.message_handler(state=ReminderForm.waiting_daily_time)
async def set_daily_reminder_time(message: types.Message, state: FSMContext):
    try:
        t = dt.strptime(message.text.strip(), "%H:%M").time()
        await db.update_reminder_setting(message.from_user.id, "daily_reminder_time", t)
        await message.reply(f"Daily reminder time set to {t.strftime('%H:%M')}")
    except ValueError:
        await message.reply("❌ Invalid format. Use HH:MM (e.g., 08:00 or 18:30). Try again.")
        return
    await state.finish()
    await send_reminder_menu(message, message.from_user.id)

@dp.callback_query_handler(lambda c: c.data == "open_email_settings")
async def open_email_settings(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_reminder_settings(user_id)
    email = settings['email'] or "Not set"
    enabled = settings['email_enabled']

    text = (
        f"📧 <b>Email Notifications</b>\n\n"
        f"Current email: {email}\n"
        f"Notifications: {'✅ Enabled' if enabled else '❌ Disabled'}\n\n"
        f"Use the buttons below to configure your email settings."
    )

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🔔/🔕 Toggle Email Notifications", callback_data="toggle_email_notifications"),
        InlineKeyboardButton("✏️ Set/Change Email Address", callback_data="change_email_address"),
        InlineKeyboardButton("📨 Test Email",     callback_data="email_test"),
    )
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "toggle_email_notifications")
async def toggle_email_notifications(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_reminder_settings(user_id)
    new_val = not settings['email_enabled']
    await db.update_reminder_setting(user_id, "email_enabled", new_val)
    await callback_query.answer("Email notifications toggled.")
    await open_email_settings(callback_query)

@dp.callback_query_handler(lambda c: c.data == "change_email_address")
async def ask_email_address(callback_query: types.CallbackQuery, state: FSMContext):
    await EmailForm.waiting_email.set()
    await bot.send_message(callback_query.from_user.id, "📧 Enter your new email address:")
    await callback_query.answer()

@dp.message_handler(state=EmailForm.waiting_email)
async def set_email_address(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    email = message.text.strip()
    await db.update_reminder_setting(user_id, "email", email)
    await message.reply(f"✅ Email updated to: {email}")
    await state.finish()
    await send_reminder_menu(message, user_id)

# Helper to redraw the menu
async def send_reminder_menu(message_or_msg, user_id):
    user_tz = await db.get_user_timezone(user_id)
    now = dt.now(pytz.UTC).astimezone(user_tz)
    today = now.date()

    schedules = await db.get_schedule(user_id, today.strftime("%Y-%m-%d"))
    tasks = await db.get_tasks_by_deadline(user_id, today)
    settings = await db.get_reminder_settings(user_id)

    offset = settings['pre_event_offset_minutes']
    daily_on = settings['daily_reminder_enabled']
    daily_time = settings['daily_reminder_time'].strftime('%H:%M')
    email_on = settings['email_enabled']

    def fmt_s():
        return "\n".join(f" • {e} at {t}" for e, t in schedules) or " —"

    def fmt_t():
        return "\n".join(f" • {task} ({cat}) – {dl.astimezone(user_tz).strftime('%H:%M')}" for task, dl, cat in tasks) or " —"

    text = (
        f"📅 <b>Today's Events</b>\n{fmt_s()}\n\n"
        f"📝 <b>Today's Tasks</b>\n{fmt_t()}\n\n"
        f"🔧 <b>Reminder Settings</b>\n"
        f"• ⏱ Pre-event reminder: {offset} min before\n"
        f"• 📆 Daily task reminder: {'✅' if daily_on else '❌'} at {daily_time}\n"
        f"• 📧 Email delivery: {'✅' if email_on else '❌'}\n"
        f"\nUse the buttons below to customize."
    )

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("⏱ Set pre-event reminder offset", callback_data="set_pre_event_offset"),
        InlineKeyboardButton("📆 Toggle daily task reminder", callback_data="toggle_daily_reminder"),
        InlineKeyboardButton("🕒 Change daily reminder time", callback_data="set_daily_reminder_time"),
        InlineKeyboardButton("📧 Email Notifications", callback_data="open_email_settings"),
    )

    if isinstance(message_or_msg, types.Message):
        await message_or_msg.reply(text, parse_mode="HTML", reply_markup=kb)
    else:
        await bot.send_message(message_or_msg.chat.id, text, parse_mode="HTML", reply_markup=kb)
