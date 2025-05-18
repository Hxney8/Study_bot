from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.callback_data import CallbackData


# Main menu
main_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
main_menu.add(KeyboardButton("📅 Schedule"), KeyboardButton("📝 Tasks"))
main_menu.add(KeyboardButton("🔔 Reminders/📧 Email Notifications"), KeyboardButton("📚 Materials"))
main_menu.add(KeyboardButton("📊 Grade Calculator"), KeyboardButton("📄 File Converter"))
main_menu.add(KeyboardButton("🎲 Ticket Generator"), KeyboardButton("👨‍🏫 Subjects & Teachers"))
main_menu.add(KeyboardButton("🌐 Set Timezone"))

schedule_time_adjustment_cb = CallbackData("schedule_time_adjust", "action", "value")

def get_date_adjustment_keyboard(year, month, day):
    keyboard = InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        InlineKeyboardButton("+ Day", callback_data="date_plus_day"),
        InlineKeyboardButton("+ Month", callback_data="date_plus_month"),
        InlineKeyboardButton("+ Year", callback_data="date_plus_year"),
    )
    keyboard.add(
        InlineKeyboardButton("- Day", callback_data="date_minus_day"),
        InlineKeyboardButton("- Month", callback_data="date_minus_month"),
        InlineKeyboardButton("- Year", callback_data="date_minus_year"),
    )
    keyboard.add(
        InlineKeyboardButton("Confirm", callback_data="date_confirm"),
        InlineKeyboardButton("Manual Input", callback_data="date_manual"),
    )
    return keyboard

def get_time_adjustment_keyboard(hour: int, minute: int) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=3)

    keyboard.row(
        InlineKeyboardButton("⬆️ Hour",
            callback_data=schedule_time_adjustment_cb.new(action="hour_increase", value="1")),
        InlineKeyboardButton(f"{hour:02d}:{minute:02d}", callback_data="ignore"),
        InlineKeyboardButton("⬆️ Min",
            callback_data=schedule_time_adjustment_cb.new(action="minute_increase", value="1")),
    )
    keyboard.row(
        InlineKeyboardButton("⬇️ Hour",
            callback_data=schedule_time_adjustment_cb.new(action="hour_decrease", value="1")),
        InlineKeyboardButton("Confirm",
            callback_data=schedule_time_adjustment_cb.new(action="confirm", value="0")),
        InlineKeyboardButton("⬇️ Min",
            callback_data=schedule_time_adjustment_cb.new(action="minute_decrease", value="1")),
    )
    keyboard.add(
        InlineKeyboardButton("✏️ Manual Input",
            callback_data=schedule_time_adjustment_cb.new(action="manual", value="0"))
    )
    return keyboard
