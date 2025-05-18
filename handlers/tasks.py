from aiogram import types
from aiogram.dispatcher import FSMContext
from datetime import datetime, time, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import calendar
from states.forms import TaskForm
from services.scheduler import schedule_task_reminders
from keyboards.common import get_date_adjustment_keyboard, get_time_adjustment_keyboard
from database.db import db
from loader import bot, dp, logger
from keyboards.common import schedule_time_adjustment_cb


async def show_task_menu(message: types.Message):
    user_id = message.from_user.id
    user_tz = await db.get_user_timezone(user_id)
    today = datetime.now(user_tz).date()
    tomorrow = today + timedelta(days=1)

    def fmt(rows):
        return "\n".join(f" • {t} ({c}) – {d.astimezone(user_tz).strftime('%H:%M')}" for t, d, c in rows) or " —"

    today_tasks = await db.get_tasks_by_deadline(user_id, today)
    tomorrow_tasks = await db.get_tasks_by_deadline(user_id, tomorrow)

    await message.reply(
        f"📝 <b>Today</b>  ({today})\n{fmt(today_tasks)}\n\n"
        f"📝 <b>Tomorrow</b> ({tomorrow})\n{fmt(tomorrow_tasks)}",
        parse_mode="HTML"
    )

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("View", callback_data="view_tasks"),
        InlineKeyboardButton("Add", callback_data="add_task"),
        InlineKeyboardButton("Edit/Delete", callback_data="edit_task"),
    )
    await message.reply("What to do with tasks?", reply_markup=kb)

@dp.callback_query_handler(
    lambda c: c.data in [
        "date_minus_day", "date_minus_month", "date_minus_year",
        "date_plus_day", "date_plus_month", "date_plus_year",
        "date_confirm", "date_manual"
    ],
    state=TaskForm.deadline
)
async def process_task_deadline_adjustment(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    action = callback_query.data  # Renamed to avoid overwriting state_data

    async with state.proxy() as state_data:
        selected_date = state_data['selected_date']

        if action == "date_minus_day":
            selected_date -= timedelta(days=1)
        elif action == "date_plus_day":
            selected_date += timedelta(days=1)
        elif action == "date_minus_month":
            if selected_date.month == 1:
                selected_date = selected_date.replace(year=selected_date.year - 1, month=12)
            else:
                selected_date = selected_date.replace(month=selected_date.month - 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif action == "date_plus_month":
            if selected_date.month == 12:
                selected_date = selected_date.replace(year=selected_date.year + 1, month=1)
            else:
                selected_date = selected_date.replace(month=selected_date.month + 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif action == "date_minus_year":
            selected_date = selected_date.replace(year=selected_date.year - 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif action == "date_plus_year":
            selected_date = selected_date.replace(year=selected_date.year + 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif action == "date_confirm":
            state_data['deadline'] = selected_date.strftime("%Y-%m-%d")
            if 'selected_time' not in state_data:
                user_timezone = await db.get_user_timezone(user_id)
                now_local = datetime.now(user_timezone)
                state_data['selected_time'] = now_local.time().replace(second=0, microsecond=0)
            selected_time = state_data['selected_time']
            keyboard = get_time_adjustment_keyboard(selected_time.hour, selected_time.minute)
            await TaskForm.time.set()
            await bot.send_message(user_id, f"Select time: {selected_time.strftime('%H:%M')}", reply_markup=keyboard)
            await bot.answer_callback_query(callback_query.id)
            return
        elif action == "date_manual":
            await TaskForm.deadline_manual.set()
            await bot.send_message(user_id, "Enter the deadline manually (yyyy-mm-dd):")
            await bot.answer_callback_query(callback_query.id)
            return

        state_data['selected_date'] = selected_date
        keyboard = get_date_adjustment_keyboard(
            selected_date.year, selected_date.month, selected_date.day
        )
        await bot.edit_message_text(
            f"Select deadline: {selected_date.strftime('%Y-%m-%d')}",
            chat_id=user_id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard
        )

    await bot.answer_callback_query(callback_query.id)




@dp.callback_query_handler(schedule_time_adjustment_cb.filter(), state=TaskForm.time)
async def process_task_time_adjustment(callback_query: types.CallbackQuery, state: FSMContext, callback_data: dict):
    user_id = callback_query.from_user.id
    action = callback_data.get("action")
    value = int(callback_data.get("value", 0))

    async with state.proxy() as state_data:
        selected_time = state_data.get("selected_time")
        if not isinstance(selected_time, time):
            user_tz = await db.get_user_timezone(user_id)
            now = datetime.now(user_tz)
            selected_time = now.time().replace(second=0, microsecond=0)

        hour, minute = selected_time.hour, selected_time.minute

        if action == "hour_increase":
            hour = (hour + value) % 24
        elif action == "hour_decrease":
            hour = (hour - value) % 24
        elif action == "minute_increase":
            minute = (minute + value) % 60
        elif action == "minute_decrease":
            minute = (minute - value) % 60

        state_data["selected_time"] = time(hour, minute)
        keyboard = get_time_adjustment_keyboard(hour, minute)

        if action == "manual":
            await TaskForm.time_manual.set()
            await bot.send_message(user_id, "Enter the time manually (HH:MM):")
            await callback_query.answer()
            return

        if action == "confirm":
            user_timezone = await db.get_user_timezone(user_id)
            naive_dt = datetime.combine(state_data["selected_date"], state_data["selected_time"])
            user_timezone = await db.get_user_timezone(user_id)
            localized_dt = user_timezone.localize(naive_dt)
            state_data['deadline_obj'] = localized_dt
            state_data['deadline'] = localized_dt.strftime("%Y-%m-%d %H:%M %z")

            await TaskForm.category.set()
            await bot.send_message(user_id, "Enter the category (homework/project/exam):")
            return

        try:
            await bot.edit_message_text(
                f"Select time: {hour:02d}:{minute:02d}",
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard
            )
        except Exception as e:
            await bot.send_message(user_id, f"Select time: {hour:02d}:{minute:02d}", reply_markup=keyboard)

    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=TaskForm.deadline_manual)
async def process_task_deadline_manual_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    date_str = message.text.strip()
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        async with state.proxy() as data:
            data['selected_date'] = date_obj
            data['selected_time'] = time(8, 0)  # Default 08:00
        await TaskForm.time.set()
        keyboard = get_time_adjustment_keyboard(8, 0)
        await message.reply("Select time:", reply_markup=keyboard)
    except ValueError:
        await message.reply("Invalid date format. Use YYYY-MM-DD (e.g., 2025-05-04). Try again.")

@dp.callback_query_handler(lambda c: c.data == "date_confirm", state=TaskForm.deadline)
async def handle_task_date_confirm(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    async with state.proxy() as state_data:
        selected_date = state_data['selected_date']
        state_data['selected_date'] = selected_date
        state_data['selected_time'] = time(8, 0)
        await TaskForm.time.set()
        keyboard = get_time_adjustment_keyboard(8, 0)
        await bot.send_message(user_id, f"Select time:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "view_tasks")
async def process_view_tasks(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'view_tasks'")
    try:
        tasks = await db.get_tasks(user_id)
        if tasks:
            response = "Your tasks:\n"
            for task, deadline, category in tasks:
                user_timezone = await db.get_user_timezone(user_id)
                local_deadline = deadline.astimezone(user_timezone)
                response += f"- {task} ({category}), deadline: {local_deadline.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            response = "No tasks yet!"
        await bot.send_message(user_id, response)
        logger.info(f"User {user_id} viewed tasks")
    except Exception as e:
        logger.error(f"Error viewing tasks for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading tasks!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "add_task")
async def process_add_task(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'add_task', current state: {await state.get_state()}")
    await TaskForm.task.set()
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(user_id, "Enter the task (e.g., Write an essay):")
    logger.info(f"User {user_id} moved to TaskForm:task")

@dp.message_handler(state=TaskForm.task)
async def process_task(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    task = message.text.strip()
    logger.info(f"User {user_id} entered task '{task}', state: {await state.get_state()}")
    try:
        if not task:
            logger.warning(f"User {user_id} entered empty task")
            await message.reply("Task cannot be empty! Try again or use /cancel.")
            return
        async with state.proxy() as data:
            data['task'] = task
        await TaskForm.deadline.set()
        async with state.proxy() as data:
            if 'selected_date' not in data:
                user_timezone = await db.get_user_timezone(user_id)
                data['selected_date'] = datetime.now(user_timezone).date()
            selected_date = data['selected_date']
        keyboard = get_date_adjustment_keyboard(selected_date.year, selected_date.month, selected_date.day)
        await message.reply(f"Select deadline: {selected_date.strftime('%Y-%m-%d')}", reply_markup=keyboard)
        logger.info(f"User {user_id} moved to TaskForm:deadline")
    except Exception as e:
        logger.error(f"Error in process_task for user {user_id}: {str(e)}")
        await message.reply("Error! Use /cancel and try again.")
        await state.finish()

@dp.message_handler(state=TaskForm.category)
async def process_category(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    category = message.text.strip()
    logger.info(f"User {user_id} entered category '{category}'")

    if not category:
        await message.reply("Category cannot be empty! Try again or use /cancel.")
        return

    async with state.proxy() as data:
        task = data['task']
        category = data['category'] = category
        edit_id = data.get('edit_id')
        deadline = data.get('deadline_obj')

        if edit_id:
            await db.update_task(edit_id, task, deadline, category)
            await message.reply("Task updated!")
        else:
            await db.add_task(user_id, task, deadline, category)
            await schedule_task_reminders(user_id, task, deadline)
            await message.reply("Task added! I'll remind you both 1 hour before and at 08:00 on due date.")

    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "edit_task")
async def process_edit_task(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'edit_task'")
    try:
        tasks = await db.get_all_tasks(user_id)
        if not tasks:
            await bot.send_message(user_id, "You have no tasks!")
            logger.info(f"User {user_id} has no tasks")
        else:
            keyboard = InlineKeyboardMarkup(row_width=1)
            for task_id, task, deadline, category in tasks:
                keyboard.add(InlineKeyboardButton(
                    f"{task} ({category}, deadline: {deadline})", callback_data=f"task_{task_id}"
                ))
            await bot.send_message(user_id, "Choose a task to edit/delete:", reply_markup=keyboard)
            logger.info(f"User {user_id} viewed edit task options")
    except Exception as e:
        logger.error(f"Error in process_edit_task for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading tasks!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("task_"))
async def process_task_action(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    task_id = int(callback_query.data.replace("task_", ""))
    logger.info(f"User {user_id} selected task {task_id}")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Edit", callback_data=f"edit_task_{task_id}"))
    keyboard.add(InlineKeyboardButton("Delete", callback_data=f"delete_task_{task_id}"))
    await bot.send_message(user_id, "What to do with the task?", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("edit_task_"))
async def process_edit_task_form(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    task_id = int(callback_query.data.replace("edit_task_", ""))
    logger.info(f"User {user_id} editing task {task_id}")
    try:
        tasks = await db.get_all_tasks(user_id)
        task = next((t for t in tasks if t[0] == task_id), None)
        if task:
            _, task_name, deadline_str, category = task
            selected_date = datetime.strptime(deadline_str, "%Y-%m-%d").date()
            await state.update_data(edit_id=task_id, selected_date=selected_date)
            await TaskForm.task.set()
            await bot.send_message(user_id, "Enter the new task name:")
            logger.info(f"User {user_id} moved to TaskForm:task")
        else:
            await bot.send_message(user_id, "Task not found!")
            await state.finish()
    except Exception as e:
        logger.error(f"Error in process_edit_task_form for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error editing task!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_task_"))
async def process_delete_task(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    task_id = int(callback_query.data.replace("delete_task_", ""))
    logger.info(f"User {user_id} deleting task {task_id}")
    try:
        await db.delete_task(task_id)
        await bot.send_message(user_id, "Task deleted!")
        logger.info(f"User {user_id} deleted task {task_id}")
    except Exception as e:
        logger.error(f"Error deleting task for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error deleting task!")
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=TaskForm.time_manual)
async def process_task_time_manual_input(message: types.Message, state: FSMContext):
    """
    User typed HH:MM for task deadline.
    """
    try:
        hh_mm = datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.reply("❌ Invalid format. Time should look like 14:30")
        return

    async with state.proxy() as data:
        data["selected_time"] = hh_mm
        user_tz = await db.get_user_timezone(message.from_user.id)
        naive_dt = datetime.combine(data["selected_date"], hh_mm)
        data["deadline_obj"] = user_tz.localize(naive_dt)

    await TaskForm.category.set()
    await message.reply("Enter a category (e.g., homework / project / exam):")