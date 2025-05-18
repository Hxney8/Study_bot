from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime as dt, timedelta, time # datetime as dt
import calendar
from aiogram.utils.callback_data import CallbackData
from keyboards.common import get_date_adjustment_keyboard, get_time_adjustment_keyboard, schedule_time_adjustment_cb
from states.forms import ScheduleForm
from services.utils import parse_datetime
from database.db import db
from loader import bot, dp, logger


async def show_schedule_menu(message: types.Message):
    user_id = message.from_user.id
    user_tz = await db.get_user_timezone(user_id)
    today = dt.now(user_tz).date()
    tomorrow = today + timedelta(days=1)

    def fmt(rows):
        return "\n".join(f" • {e} at {t}" for e, t in rows) or " —"

    today_rows = await db.get_schedule(user_id, today.strftime("%Y-%m-%d"))
    tomorrow_rows = await db.get_schedule(user_id, tomorrow.strftime("%Y-%m-%d"))

    await message.reply(
        f"📅 <b>Today</b>  ({today})\n{fmt(today_rows)}\n\n"
        f"📅 <b>Tomorrow</b> ({tomorrow})\n{fmt(tomorrow_rows)}",
        parse_mode="HTML"
    )

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("View", callback_data="view_schedule"),
        InlineKeyboardButton("Add", callback_data="add_schedule"),
        InlineKeyboardButton("Edit/Delete", callback_data="edit_schedule"),
    )

    await message.reply("What to do with the schedule?", reply_markup=kb)
    logger.info(f"User {user_id} opened the schedule menu")

@dp.callback_query_handler(lambda c: c.data == "view_schedule")
async def process_view_schedule(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info("User %s clicked 'view_schedule'", user_id)

    try:
        rows = await db.get_all_schedules(user_id)
        if rows:
            reply = "📅 <b>All scheduled events</b>:\n\n"
            for _, event, d, t in rows:
                reply += f" • {event}  —  {d} {t}\n"
        else:
            reply = "You have no events yet!"

        await bot.send_message(user_id, reply, parse_mode="HTML")
    except Exception as e:
        logger.error("Error viewing schedule for user %s: %s", user_id, e)
        await bot.send_message(user_id, "Error loading schedule!")

    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "add_schedule")
async def process_add_schedule(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'add_schedule', current state: {await state.get_state()}")
    await ScheduleForm.event.set()
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(user_id, "Enter the event name (e.g., Math lecture):")
    logger.info(f"User {user_id} moved to ScheduleForm:event")

@dp.message_handler(state=ScheduleForm.event)
async def process_event(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    event = message.text.strip()
    logger.info(f"User {user_id} entered event '{event}', state: {await state.get_state()}")
    try:
        if not event:
            logger.warning(f"User {user_id} entered empty event")
            await message.reply("Event name cannot be empty! Try again or use /cancel.")
            return

        async with state.proxy() as data:
            data['event'] = event

        await ScheduleForm.date.set()

        user_timezone = await db.get_user_timezone(user_id)
        current_date = dt.now(user_timezone).date()

        async with state.proxy() as data:
            if 'selected_date' not in data:
                data['selected_date'] = current_date
            selected_date = data['selected_date']

        keyboard = get_date_adjustment_keyboard(selected_date.year, selected_date.month, selected_date.day)
        await message.reply(f"📅 Select date (timezone: {user_timezone.zone}): {selected_date.strftime('%Y-%m-%d')}", reply_markup=keyboard)
        logger.info(f"User {user_id} moved to ScheduleForm:date")
    except Exception as e:
        logger.error(f"Error in process_event for user {user_id}: {str(e)}")
        await message.reply("Error! Use /cancel and try again.")
        await state.finish()


@dp.callback_query_handler(lambda c: c.data == "edit_schedule")
async def process_edit_schedule(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'edit_schedule'")
    try:
        schedules = await db.get_all_schedules(user_id)
        if not schedules:
            await bot.send_message(user_id, "You have no events!")
            logger.info(f"User {user_id} has no schedules")
        else:
            keyboard = InlineKeyboardMarkup(row_width=1)
            for schedule_id, event, date, time in schedules:
                keyboard.add(InlineKeyboardButton(
                    f"{event} ({date} {time})", callback_data=f"schedule_{schedule_id}"
                ))
            await bot.send_message(user_id, "Choose an event to edit/delete:", reply_markup=keyboard)
            logger.info(f"User {user_id} viewed edit schedule options")
    except Exception as e:
        logger.error(f"Error in process_edit_schedule for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading schedules!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("schedule_"))
async def process_schedule_action(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    schedule_id = int(callback_query.data.replace("schedule_", ""))
    logger.info(f"User {user_id} selected schedule {schedule_id}")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Edit", callback_data=f"edit_schedule_{schedule_id}"))
    keyboard.add(InlineKeyboardButton("Delete", callback_data=f"delete_schedule_{schedule_id}"))
    await bot.send_message(user_id, "What to do with the event?", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("edit_schedule_"))
async def process_edit_schedule_form(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    schedule_id = int(callback_query.data.replace("edit_schedule_", ""))
    logger.info(f"User {user_id} editing schedule {schedule_id}")
    try:
        schedules = await db.get_all_schedules(user_id)
        schedule = next((s for s in schedules if s[0] == schedule_id), None)
        if schedule:
            _, event, date_str, time_str = schedule
            selected_date = dt.strptime(date_str, "%Y-%m-%d").date()
            selected_time = dt.strptime(time_str, "%H:%M").time()
            await state.update_data(edit_id=schedule_id, selected_date=selected_date, selected_time=selected_time)
            await ScheduleForm.event.set()
            await bot.send_message(user_id, "Enter the new event name:")
        else:
            await bot.send_message(user_id, "Schedule not found!")
            await state.finish()
    except Exception as e:
        logger.error(f"Error in process_edit_schedule_form for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error editing event!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_schedule_"))
async def process_delete_schedule(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    schedule_id = int(callback_query.data.replace("delete_schedule_", ""))
    logger.info(f"User {user_id} deleting schedule {schedule_id}")
    try:
        await db.delete_schedule(schedule_id)
        await bot.send_message(user_id, "Event deleted!")
        logger.info(f"User {user_id} deleted schedule {schedule_id}")
    except Exception as e:
        logger.error(f"Error deleting schedule for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error deleting event!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data in ["date_minus_day", "date_minus_month", "date_minus_year", "date_plus_day", "date_plus_month", "date_plus_year", "date_confirm", "date_manual"], state=ScheduleForm.date)
async def process_schedule_date_adjustment(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = callback_query.data
    async with state.proxy() as state_data:
        selected_date = state_data['selected_date']
        if data == "date_minus_day":
            selected_date -= timedelta(days=1)
        elif data == "date_plus_day":
            selected_date += timedelta(days=1)
        elif data == "date_minus_month":
            if selected_date.month == 1:
                selected_date = selected_date.replace(year=selected_date.year - 1, month=12)
            else:
                selected_date = selected_date.replace(month=selected_date.month - 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif data == "date_plus_month":
            if selected_date.month == 12:
                selected_date = selected_date.replace(year=selected_date.year + 1, month=1)
            else:
                selected_date = selected_date.replace(month=selected_date.month + 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif data == "date_minus_year":
            selected_date = selected_date.replace(year=selected_date.year - 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif data == "date_plus_year":
            selected_date = selected_date.replace(year=selected_date.year + 1)
            last_day = calendar.monthrange(selected_date.year, selected_date.month)[1]
            if selected_date.day > last_day:
                selected_date = selected_date.replace(day=last_day)
        elif data == "date_manual":
            # Ask the user to type the date
            await ScheduleForm.date_manual.set()
            await bot.send_message(
                user_id,
                "Enter the date manually (YYYY-MM-DD):"
            )
            await bot.answer_callback_query(callback_query.id)
            return
        elif data == "date_confirm":
            state_data['date'] = selected_date.strftime("%Y-%m-%d")  # Store date as string
            await ScheduleForm.time.set()

            if 'selected_time' not in state_data or not isinstance(state_data['selected_time'], time):
                user_timezone = await db.get_user_timezone(user_id)
                now = dt.now(user_timezone).time().replace(second=0, microsecond=0)
                state_data['selected_time'] = now

            selected_time = state_data['selected_time']
            keyboard = get_time_adjustment_keyboard(selected_time.hour, selected_time.minute)
            await bot.send_message(
                user_id,
                f"Select time: {selected_time.strftime('%H:%M')}",
                reply_markup=keyboard
            )
            await bot.answer_callback_query(callback_query.id)
            return
        state_data['selected_date'] = selected_date
        keyboard = get_date_adjustment_keyboard(selected_date.year, selected_date.month, selected_date.day)
        try:
            await bot.edit_message_text(
                f"Select date: {selected_date.strftime('%Y-%m-%d')}",
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Failed to edit date message for user {user_id}: {str(e)}")
            await bot.send_message(user_id, f"Select date: {selected_date.strftime('%Y-%m-%d')}", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=ScheduleForm.date_manual)
async def process_schedule_date_manual_input(message: types.Message, state: FSMContext):
    """
    User has typed a date (YYYY‑MM‑DD). Validate it, store it,
    then show the *time* keyboard.
    """
    try:
        selected_date = dt.strptime(message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        await message.reply("❌ Invalid format. Please enter date like 2025-05-12")
        return

    async with state.proxy() as data:
        data["selected_date"] = selected_date

    # move straight to the time picker
    await ScheduleForm.time.set()
    now_local = dt.now(await db.get_user_timezone(message.from_user.id))
    keyboard = get_time_adjustment_keyboard(now_local.hour, now_local.minute)
    await message.reply(
        f"Select the time for {selected_date.strftime('%Y-%m-%d')}:",
        reply_markup=keyboard
    )

schedule_time_adjustment_cb = CallbackData("schedule_time_adjust", "action", "value")

@dp.callback_query_handler(schedule_time_adjustment_cb.filter(), state=ScheduleForm.time)
async def process_schedule_time_adjustment(callback_query: types.CallbackQuery, state: FSMContext, callback_data: dict):
    user_id = callback_query.from_user.id
    logger.info(f"Processing time adjustment for user {user_id}, callback_data: {callback_data}")

    if not all(key in callback_data for key in ["action", "value"]):
        logger.error(f"Invalid callback_data for user {user_id}: {callback_data}")
        await bot.send_message(user_id, "Error: Invalid time adjustment. Start over with /schedule.")
        await state.finish()
        await callback_query.answer()
        return

    action = callback_data["action"]
    try:
        value = int(callback_data["value"])
    except ValueError:
        logger.error(f"Invalid value in callback_data for user {user_id}: {callback_data['value']}")
        await bot.send_message(user_id, "Error: Invalid time adjustment value.")
        await state.finish()
        await callback_query.answer()
        return

    async with state.proxy() as state_data:
        event = state_data.get('event')
        date = state_data.get('date')
        selected_time = state_data.get('selected_time')

        if not event or not date:
            logger.error(f"Missing event or date for user {user_id}: event={event}, date={date}")
            await bot.send_message(user_id, "Error: Event or date missing. Start over with /schedule.")
            await state.finish()
            await callback_query.answer()
            return

        # Get user timezone for safe fallback
        user_timezone = await db.get_user_timezone(user_id)

        if not isinstance(selected_time, time):
            logger.warning(f"Invalid selected_time for user {user_id}: {selected_time}. Using current time.")
            selected_time = dt.now(user_timezone).time().replace(second=0, microsecond=0)
            state_data['selected_time'] = selected_time

        hour, minute = selected_time.hour, selected_time.minute
        logger.info(f"Current time for user {user_id}: {hour:02d}:{minute:02d}, action={action}, value={value}")

        if action == "manual":
            await ScheduleForm.time_manual.set()
            await bot.send_message(user_id, "Enter the time manually (HH:MM):")
            await callback_query.answer()
            return

        if action in ["hour_increase", "hour_decrease", "minute_increase", "minute_decrease"]:
            if action == "hour_increase":
                hour = (hour + value) % 24
            elif action == "hour_decrease":
                hour = (hour - value) % 24
            elif action == "minute_increase":
                minute = (minute + value) % 60
            elif action == "minute_decrease":
                minute = (minute - value) % 60

            state_data['selected_time'] = time(hour, minute)
            keyboard = get_time_adjustment_keyboard(hour, minute)

            try:
                await bot.edit_message_text(
                    f"Select time: {hour:02d}:{minute:02d}",
                    chat_id=user_id,
                    message_id=callback_query.message.message_id,
                    reply_markup=keyboard
                )
                logger.info(f"Time updated for user {user_id}: {hour:02d}:{minute:02d}")
            except Exception as e:
                logger.error(f"Error editing time message for user {user_id}: {str(e)}")
                await bot.send_message(user_id, f"Select time: {hour:02d}:{minute:02d}", reply_markup=keyboard)

        elif action == "confirm":
            try:
                time_str = f"{hour:02d}:{minute:02d}"
                logger.info(f"Confirming event for user {user_id}: event={event}, date={date}, time={time_str}")
                event_datetime = await parse_datetime(date, time_str, user_id)

                # Enforce timezone-awareness if parse_datetime fails to include tzinfo
                if event_datetime.tzinfo is None:
                    event_datetime = user_timezone.localize(event_datetime)

                if event_datetime < dt.now(event_datetime.tzinfo):
                    logger.warning(f"Past event detected for user {user_id}: {event_datetime}")
                    await bot.send_message(user_id, "Cannot schedule events in the past!")
                    await state.finish()
                    await callback_query.answer()
                    return

                edit_id = state_data.get('edit_id')
                if edit_id:
                    logger.info(f"Updating schedule ID {edit_id} for user {user_id}")
                    await db.update_schedule(edit_id, event, event_datetime)
                    await bot.send_message(user_id, "Event updated successfully!")
                else:
                    logger.info(f"Adding new event for user {user_id}")
                    await db.add_event(user_id, event, event_datetime)
                    await bot.send_message(user_id, "Event added! I'll remind you one hour before.")

                await state.finish()
                try:
                    await bot.delete_message(user_id, callback_query.message.message_id)
                except Exception as e:
                    logger.warning(f"Failed to delete time selection message for user {user_id}: {str(e)}")
                logger.info(f"Event confirmed for user {user_id}, state cleared")

            except ValueError as e:
                logger.error(f"Parsing error for user {user_id}: {str(e)}")
                await bot.send_message(user_id, "Error: Invalid date or time format.")
                await state.finish()
            except Exception as e:
                logger.error(f"Error confirming event for user {user_id}: {str(e)}")
                await bot.send_message(user_id, "Error saving event. Try again or use /cancel.")
                await state.finish()
        else:
            logger.error(f"Unknown action for user {user_id}: {action}")
            await bot.send_message(user_id, "Error: Unknown action. Start over with /schedule.")
            await state.finish()

    await callback_query.answer()


@dp.message_handler(state=ScheduleForm.time_manual)
async def process_schedule_time_manual_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    time_str = message.text.strip()
    logger.info(f"User {user_id} entered time: {time_str}")
    
    async with state.proxy() as state_data:
        event = state_data.get('event')
        date = state_data.get('date')
        
        if not event or not date:
            logger.error(f"Missing event or date for user {user_id}: event={event}, date={date}")
            await message.reply("Error: Event or date missing. Start over with /schedule.")
            await state.finish()
            return

        try:
            # Combine date and time string into datetime object (timezone-aware)
            event_datetime = await parse_datetime(date, time_str, user_id)

            # Ensure datetime is timezone-aware (fallback in case parse_datetime returns naive datetime)
            if event_datetime.tzinfo is None:
                user_timezone = await db.get_user_timezone(user_id)
                event_datetime = user_timezone.localize(event_datetime)

            # Check if event is in the past
            if event_datetime < dt.now(event_datetime.tzinfo):
                logger.warning(f"Past event detected for user {user_id}: {event_datetime}")
                await message.reply("Cannot schedule events in the past!")
                await state.finish()
                return

            # Check if this is an update or a new event
            edit_id = state_data.get('edit_id')
            if edit_id:
                logger.info(f"Updating schedule ID {edit_id} for user {user_id}")
                await db.update_schedule(edit_id, event, event_datetime)
                await message.reply("Event updated successfully!")
            else:
                logger.info(f"Adding new event for user {user_id}")
                await db.add_event(user_id, event, event_datetime)
                await message.reply("Event added! I'll remind you one hour before.")
            
            await state.finish()
            logger.info(f"Event confirmed for user {user_id}, state cleared")

        except ValueError as e:
            logger.error(f"Time parsing error for user {user_id}: {str(e)}")
            await message.reply("Invalid time format. Use HH:MM (e.g., 14:30).")
        except Exception as e:
            logger.error(f"Error processing time for user {user_id}: {str(e)}")
            await message.reply("Error saving event. Try again or use /cancel.")
            await state.finish()