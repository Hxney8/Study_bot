from datetime import datetime, timedelta, date, time
from apscheduler.triggers.date import DateTrigger
from database.db import db
import pytz
from loader import bot, logger, scheduler
from services.utils import slugify, format_local, create_styled_email
from services.reminder_engine import _maybe_send_email, remind_event, remind_task


async def send_due_reminders():
    """
    Runs every minute (APS-scheduler). For each user:
        • pre-event schedule reminders (configurable, once only)
        • exact-time schedule reminders (once only)
        • exact-time task reminders (once only)
        • daily summary at user-defined time
    """
    logger.info("Running reminder job…")
    now_utc = datetime.now(pytz.UTC)

    users = await db.get_all_users()
    for user_id in users:
        try:
            user_tz = await db.get_user_timezone(user_id)
            settings = await db.get_reminder_settings(user_id)
            now_local = now_utc.astimezone(user_tz)
            target_minute = now_local.replace(second=0, microsecond=0)

            pre_offset_min = settings['pre_event_offset_minutes']
            daily_enabled = settings['daily_reminder_enabled']
            email_enabled = settings['email_enabled']
            daily_reminder_time = settings['daily_reminder_time']

            # ── Pre-event reminders ─────────────────────────
            if pre_offset_min > 0:
                offset_td = timedelta(minutes=pre_offset_min)
                pre_event_target = target_minute + offset_td
                events = await db.get_schedule(user_id, pre_event_target.strftime("%Y-%m-%d"))
                for title, time_str in events:
                    if time_str == pre_event_target.strftime("%H:%M"):
                        text = f"⏰ Schedule reminder: “{title}” starts at {time_str}!"
                        await bot.send_message(user_id, text)
                        if email_enabled:
                            # Plain-text content
                            plain_text = f"Schedule Reminder\n\nEvent: {title}\nTime: {time_str}"
                            # HTML content
                            html_content = (
                                "<p style='margin: 0 0 10px;'>⏰ <strong>Upcoming Event</strong></p>"
                                f"<p style='margin: 0 0 5px;'>Event: {title}</p>"
                                f"<p style='margin: 0 0 5px;'>Time: {time_str}</p>"
                            )
                            html_body = create_styled_email(f"Upcoming event: {title}", html_content)
                            await _maybe_send_email(user_id, f"Upcoming event: {title}", html_body, content_type="text/html", plain_text=plain_text)

            # ── Exact-time schedule reminders ──────────────
            due_events = await db.get_due_schedules(user_id, now_local)
            for schedule_id, title, dt in due_events:
                local_time = dt.astimezone(user_tz).strftime('%H:%M')
                text = f"🕒 Event starting now: “{title}” at {local_time}"
                await bot.send_message(user_id, text)
                if email_enabled:
                    # Plain-text content
                    plain_text = f"Event Reminder\n\nEvent: {title}\nTime: {local_time} (now)"
                    # HTML content
                    html_content = (
                        "<p style='margin: 0 0 10px;'>🕒 <strong>Event Starting Now</strong></p>"
                        f"<p style='margin: 0 0 5px;'>Event: {title}</p>"
                        f"<p style='margin: 0 0 5px;'>Time: {local_time}</p>"
                    )
                    html_body = create_styled_email(f"Event now: {title}", html_content)
                    await _maybe_send_email(user_id, f"Event now: {title}", html_body, content_type="text/html", plain_text=plain_text)
                await db.mark_schedule_reminded(schedule_id)

            # ── Exact-time task reminders ──────────────────
            due_tasks = await db.get_tasks_due_now(user_id, now_local)
            for task_id, task, deadline, category in due_tasks:
                local_deadline = deadline.astimezone(user_tz)
                text = (
                    f"📌 Task due now: “{task}” ({category}) "
                    f"at {local_deadline.strftime('%H:%M')}"
                )
                await bot.send_message(user_id, text)
                if email_enabled:
                    # Plain-text content
                    plain_text = f"Task Reminder\n\nTask: {task}\nCategory: {category}\nDue: {local_deadline.strftime('%H:%M')} (now)"
                    # HTML content
                    html_content = (
                        "<p style='margin: 0 0 10px;'>📌 <strong>Task Due Now</strong></p>"
                        f"<p style='margin: 0 0 5px;'>Task: {task}</p>"
                        f"<p style='margin: 0 0 5px;'>Category: {category}</p>"
                        f"<p style='margin: 0 0 5px;'>Due: {local_deadline.strftime('%H:%M')}</p>"
                    )
                    html_body = create_styled_email(f"Task due: {task}", html_content)
                    await _maybe_send_email(user_id, f"Task due: {task}", html_body, content_type="text/html", plain_text=plain_text)
                await db.mark_task_reminded(task_id)

            # ── Daily reminder at user-defined time ────────
            if daily_enabled:
                current_time = now_local.time().replace(second=0, microsecond=0)
                if current_time == daily_reminder_time:
                    today_tasks = await db.get_tasks_by_deadline(user_id, now_local.date())
                    today_schedules = await db.get_schedule(user_id, now_local.strftime("%Y-%m-%d"))

                    if today_tasks or today_schedules:
                        # ── Telegram Message ──
                        text_telegram = "📅 <b>Daily Reminder</b>\n\n"
                        if today_schedules:
                            text_telegram += "🗓️ <b>Today's Events</b>\n"
                            for title, time_str in today_schedules:
                                text_telegram += f" • {title} at {time_str}\n"
                            text_telegram += "\n"
                        if today_tasks:
                            text_telegram += "📝 <b>Today's Tasks</b>\n"
                            for task, deadline, category in today_tasks:
                                t = deadline.astimezone(user_tz).strftime('%H:%M')
                                text_telegram += f" • {task} ({category}) – {t}\n"

                        await bot.send_message(user_id, text_telegram.strip(), parse_mode="HTML")

                        # ── Email ──
                        # Plain-text content
                        plain_text = "Daily Reminder\n\n"
                        if today_schedules:
                            plain_text += "Today's Events:\n"
                            for title, time_str in today_schedules:
                                plain_text += f"- {title} at {time_str}\n"
                            plain_text += "\n"
                        if today_tasks:
                            plain_text += "Today's Tasks:\n"
                            for task, deadline, category in today_tasks:
                                t = deadline.astimezone(user_tz).strftime('%H:%M')
                                plain_text += f"- {task} ({category}) – {t}\n"

                        # HTML content (existing)
                        text_email = (
                            "<!DOCTYPE html>"
                            "<html lang='en'>"
                            "<head>"
                            "<meta charset='UTF-8'>"
                            "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
                            "<title>Daily Reminder</title>"
                            "</head>"
                            "<body style='font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #333333; margin: 0; padding: 20px;'>"
                            "<div style='max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border: 1px solid #dddddd; border-radius: 5px;'>"
                            "<h2 style='font-size: 18px; color: #444444; margin: 0 0 10px;'>📅 Daily Reminder</h2>"
                        )

                        if today_schedules:
                            text_email += (
                                "<h3 style='font-size: 16px; color: #444444; margin: 10px 0;'>🗓️ Today's Events</h3>"
                                "<ul style='list-style-type: disc; padding-left: 20px; margin: 0 0 15px;'>"
                            )
                            for title, time_str in today_schedules:
                                title = title.replace('<', '&lt;').replace('>', '&gt;')
                                time_str = time_str.replace('<', '&lt;').replace('>', '&gt;')
                                text_email += f"<li style='margin-bottom: 5px;'>{title} at {time_str}</li>"
                            text_email += "</ul>"

                        if today_tasks:
                            text_email += (
                                "<h3 style='font-size: 16px; color: #444444; margin: 10px 0;'>📝 Today's Tasks</h3>"
                                "<ul style='list-style-type: disc; padding-left: 20px; margin: 0 0 15px;'>"
                            )
                            for task, deadline, category in today_tasks:
                                task = task.replace('<', '&lt;').replace('>', '&gt;')
                                category = category.replace('<', '&lt;').replace('>', '&gt;')
                                t = deadline.astimezone(user_tz).strftime('%H:%M')
                                text_email += f"<li style='margin-bottom: 5px;'>{task} ({category}) – {t}</li>"
                            text_email += "</ul>"

                        text_email += (
                            "</div>"
                            "</body>"
                            "</html>"
                        )

                        if email_enabled:
                            await _maybe_send_email(user_id, "📅 Daily Reminder", text_email, content_type="text/html", plain_text=plain_text)

        except Exception as e:
            logger.error("Reminder error for user %s: %s", user_id, e)

async def schedule_reminders():
    logger.info("Scheduling reminders...")
    users = await db.get_all_users()

    for user_id in users:
        try:
            settings = await db.get_reminder_settings(user_id)
            user_tz = await db.get_user_timezone(user_id)
            now = datetime.now(user_tz)

            pre_offset = timedelta(minutes=settings['pre_event_offset_minutes'])
            daily_time = settings['daily_reminder_time']
            daily_enabled = settings['daily_reminder_enabled']

            # ────── EVENTS ──────
            schedules = await db.get_user_future_schedules(user_id)
            for sched in schedules:
                event = sched["event"]
                event_dt = sched["event_datetime"]

                if event_dt.tzinfo is None:
                    event_dt = user_tz.localize(event_dt)
                when_local = format_local(event_dt, user_tz)

                # pre‑event offset
                pre_run = event_dt - pre_offset
                if pre_run > now:
                    scheduler.add_job(
                        remind_event,
                        trigger=DateTrigger(run_date=pre_run),
                        args=[user_id, event, when_local],
                        id=f"event_offset_{user_id}_{event_dt.isoformat()}_{slugify(event)}",
                        replace_existing=True,
                    )

                # daily reminder (8am or custom time)
                if daily_enabled:
                    daily_dt = event_dt.replace(
                        hour=daily_time.hour,
                        minute=daily_time.minute,
                        second=0,
                        microsecond=0
                    )
                    if daily_dt > now:
                        scheduler.add_job(
                            remind_event,
                            trigger=DateTrigger(run_date=daily_dt),
                            args=[user_id, event, when_local],
                            id=f"event_daily_{user_id}_{event_dt.isoformat()}_{slugify(event)}",
                            replace_existing=True,
                        )

            # ────── TASKS ──────
            tasks = await db.get_tasks(user_id)
            for task_title, deadline_dt, _ in tasks:
                if isinstance(deadline_dt, date) and not isinstance(deadline_dt, datetime):
                    deadline_dt = datetime.combine(deadline_dt, time.min)
                if deadline_dt.tzinfo is None:
                    deadline_dt = user_tz.localize(deadline_dt)
                when_local = format_local(deadline_dt, user_tz)

                # pre-event offset
                pre_run = deadline_dt - pre_offset
                if pre_run > now:
                    scheduler.add_job(
                        remind_task,
                        trigger=DateTrigger(run_date=pre_run),
                        args=[user_id, task_title, when_local],
                        id=f"task_offset_{user_id}_{deadline_dt.isoformat()}_{slugify(task_title)}",
                        replace_existing=True,
                    )

                # daily reminder time (default 8am)
                if daily_enabled:
                    daily_dt = deadline_dt.replace(
                        hour=daily_time.hour,
                        minute=daily_time.minute,
                        second=0,
                        microsecond=0
                    )
                    if daily_dt > now:
                        scheduler.add_job(
                            remind_task,
                            trigger=DateTrigger(run_date=daily_dt),
                            args=[user_id, task_title, when_local],
                            id=f"task_daily_{user_id}_{deadline_dt.isoformat()}_{slugify(task_title)}",
                            replace_existing=True,
                        )

        except Exception as e:
            logger.error(f"Error scheduling reminders for user {user_id}: {e}")





async def schedule_task_reminders(user_id: int, task: str, deadline: datetime):
    settings = await db.get_reminder_settings(user_id)
    user_tz = await db.get_user_timezone(user_id)
    now = datetime.now(user_tz)

    if deadline.tzinfo is None:
        deadline = user_tz.localize(deadline)

    pre_offset = timedelta(minutes=settings['pre_event_offset_minutes'])
    daily_time = settings['daily_reminder_time']
    daily_enabled = settings['daily_reminder_enabled']
    when_local = format_local(deadline, user_tz)

    # pre-event reminder
    pre_reminder = deadline - pre_offset
    if pre_reminder > now:
        scheduler.add_job(
            remind_task,
            trigger=DateTrigger(run_date=pre_reminder),
            args=[user_id, task, deadline],
            id=f"task_offset_{user_id}_{deadline.isoformat()}_{slugify(task)}",
            replace_existing=True
        )

    # daily reminder
    if daily_enabled:
        daily_dt = deadline.replace(hour=daily_time.hour, minute=daily_time.minute, second=0, microsecond=0)
        if daily_dt > now:
            scheduler.add_job(
                remind_task,
                trigger=DateTrigger(run_date=daily_dt),
                args=[user_id, task, deadline],
                id=f"task_daily_{user_id}_{deadline.isoformat()}_{slugify(task)}",
                replace_existing=True
            )