from aiogram import types
from aiogram.dispatcher import FSMContext
import pytz
from database.db import db
from loader import dp, logger
from keyboards.common import main_menu
from states.forms import GradeForm, ConvertForm


@dp.message_handler(commands=["start"], state="*")
async def send_welcome(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.finish()
    await db.add_user(user_id)
    await message.reply(
        f"Hello, {message.from_user.first_name}! I'm StudyBot — your study assistant.\n"
        f"Choose what you want to do:",
        reply_markup=main_menu
    )
    logger.info(f"User {user_id} started bot and main menu was shown")


@dp.message_handler(commands=["cancel"], state="*")
async def cancel_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.finish()
    await message.reply("Action canceled. Choose a new option:", reply_markup=main_menu)
    logger.info(f"User {user_id} cancelled state")


@dp.message_handler(lambda message: message.text == "/health", state="*")
async def health_check(message: types.Message):
    await message.reply("✅ OK")


@dp.message_handler(
    lambda m: m.text in [
        "📅 Schedule",
        "📝 Tasks",
        "🔔 Reminders/📧 Email Notifications",
        "📚 Materials",
        "📊 Grade Calculator",
        "📄 File Converter",
        "🎲 Ticket Generator",
        "👨‍🏫 Subjects & Teachers",
        "🌐 Set Timezone",
    ],
    state="*"
)
async def handle_menu(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text
    await state.finish()

    if text == "📅 Schedule":
        from handlers.schedule import show_schedule_menu
        await show_schedule_menu(message)

    elif text == "📝 Tasks":
        from handlers.tasks import show_task_menu
        await show_task_menu(message)

    elif text == "🔔 Reminders/📧 Email Notifications":
        from handlers.reminders import send_reminder_menu
        await send_reminder_menu(message, message.from_user.id)

    elif text == "📚 Materials":
        from handlers.materials import materials_menu
        await materials_menu(message, state)

    elif text == "📊 Grade Calculator":
        await GradeForm.grades.set()
        await message.reply("Enter your grades separated by spaces (e.g., 5 4 3):")

    elif text == "📄 File Converter":
        from handlers.file_converter import show_converter_menu
        await ConvertForm.select_type.set()
        await show_converter_menu(message)

    elif text == "🎲 Ticket Generator":
        from handlers.tickets import show_ticket_menu
        await show_ticket_menu(message)

    elif text == "👨‍🏫 Subjects & Teachers":
        from handlers.subjects_teachers import mgr_root
        await mgr_root(message.chat.id, user_id=user_id)

    elif text == "🌐 Set Timezone":
        from handlers.timezone import handle_timezone_menu
        await handle_timezone_menu(message, state)

    logger.info(f"User {user_id} selected menu '{text}'")
