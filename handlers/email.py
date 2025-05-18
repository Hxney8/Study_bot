from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from loader import bot, dp, logger
from states.forms import EmailForm
from database.db import db
from services.email_service import send_email
from services.utils import create_styled_email


# ─── Email Settings Entry Point ─────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "open_email_settings")
async def open_email_settings(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_reminder_settings(user_id)
    email = settings.get('email') or "Not set"
    enabled = settings.get('email_enabled')

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
        InlineKeyboardButton("📨 Test Email", callback_data="email_test"),
    )
    await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback_query.answer()


# ─── Toggle Email ON/OFF ────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "toggle_email_notifications")
async def toggle_email_notifications(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_reminder_settings(user_id)
    new_val = not settings['email_enabled']
    await db.update_reminder_setting(user_id, "email_enabled", new_val)
    await callback_query.answer("Email notifications toggled.")
    await open_email_settings(callback_query)


# ─── Update Email Address ───────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "change_email_address")
async def ask_email_address(callback_query: CallbackQuery, state: FSMContext):
    await EmailForm.waiting_email.set()
    await bot.send_message(callback_query.from_user.id, "📧 Enter your new email address:")
    await callback_query.answer()


@dp.message_handler(state=EmailForm.waiting_email)
async def set_email_address(message: types.Message, state: FSMContext):
    email = message.text.strip()
    user_id = message.from_user.id
    await db.update_reminder_setting(user_id, "email", email)
    await message.reply(f"✅ Email updated to: {email}")
    await state.finish()

    # Optionally re-show menu
    from handlers.reminders import send_reminder_menu
    await send_reminder_menu(message, user_id)


# ─── Test Email Delivery ────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data == "email_test")
async def test_email(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    email, enabled = await db.get_email_prefs(user_id)

    if not enabled or not email:
        await callback_query.answer("Email not enabled or missing.", show_alert=True)
        return

    subject = "📨 Test Email from StudyBot"
    body_html = create_styled_email(
        "Test Email",
        "<p>This is a test email to confirm your email notification setup is working.</p>"
    )
    plain_text = "This is a test email from StudyBot."

    try:
        await send_email(email, subject, body_html, plain_text=plain_text)
        await callback_query.answer("✅ Test email sent!")
    except Exception as e:
        logger.error(f"Email test failed: {e}")
        await callback_query.answer("❌ Failed to send test email. Check server logs.", show_alert=True)
