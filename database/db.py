import asyncpg
import logging
from datetime import datetime, date, timedelta, time
import os
import pytz
import asyncio

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.dsn = os.getenv(
            'DATABASE_URL',
            'postgresql://dbusername:dbpassword@db:5432/studybot?sslmode=disable'
        )
        self.pool = None
        # Get default timezone from environment variable or fallback to UTC
        self.default_timezone = pytz.timezone('Asia/Tashkent')  # GMT+5 default
        logger.info(f"Using timezone: {self.default_timezone}")

    async def init_db(self):
            try:
                self.pool = await asyncpg.create_pool(self.dsn)
                async with self.pool.acquire() as conn:
                    # Create tables in order of dependency
                    # 1. users (referenced by many tables)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            user_id BIGINT  PRIMARY KEY,
                            timezone TEXT NOT NULL DEFAULT 'Asia/Tashkent',
                            email TEXT,
                            email_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
                            pre_event_offset_minutes INTEGER NOT NULL DEFAULT 60,
                            daily_reminder_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
                            daily_reminder_time     TIME    NOT NULL DEFAULT '08:00'
                        )
                    ''')

                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS subjects (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            name TEXT NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                        )
                    ''')

                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS teachers (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            name TEXT NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                        )
                    ''')

                    # 4. schedules (references users)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS schedules (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            event TEXT NOT NULL,
                            event_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
                            reminded BOOLEAN NOT NULL DEFAULT FALSE,
                            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                            UNIQUE (user_id, event, event_datetime)
                        )
                    ''')
                    await conn.execute('''
                        CREATE INDEX IF NOT EXISTS idx_schedules_user_datetime 
                        ON schedules (user_id, event_datetime)
                    ''')

                    # 5. tasks (references users)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS tasks (
                            id        SERIAL PRIMARY KEY,
                            user_id   BIGINT,
                            task      TEXT NOT NULL,
                            deadline  TIMESTAMP WITH TIME ZONE NOT NULL,
                            reminded  BOOLEAN NOT NULL DEFAULT FALSE,
                            category  TEXT NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                        )
                    ''')
                    await conn.execute('''
                        CREATE INDEX IF NOT EXISTS idx_tasks_user_deadline
                            ON tasks (user_id, deadline)
                    ''')
                    # 6. files (references users and subjects)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS files (
                            id               SERIAL  PRIMARY KEY,
                            user_id          BIGINT,
                            subject_id       INTEGER          NULL,
                            telegram_file_id TEXT    NOT NULL,
                            file_name        TEXT    NOT NULL             -- searchable name
                                                DEFAULT '',
                            description      TEXT,
                            upload_date      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                            FOREIGN KEY (user_id)    REFERENCES users (user_id) ON DELETE CASCADE,
                            FOREIGN KEY (subject_id) REFERENCES subjects(id)    ON DELETE SET NULL
                        )
                    ''')

                    # 7. subject_teachers (references subjects and teachers)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS subject_teachers (
                            subject_id INTEGER,
                            teacher_id INTEGER,
                            PRIMARY KEY (subject_id, teacher_id),
                            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE,
                            FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE CASCADE
                        )
                    ''')

                    # 8. tickets (references users)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS tickets (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            subject TEXT NOT NULL,
                            ticket TEXT NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                        )
                    ''')
                    # 10. conversions (references users)
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS conversions (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            conversion_type TEXT NOT NULL,
                            timestamp TIMESTAMP NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                        )
                    ''')

                    logger.info("Database initialized successfully")
                    logger.info("DB pool ready: %s", self.pool)
                    return
            except Exception as e:
                    logger.error(f"Failed to initialize database after all retries {e}")

    async def _ensure_trgm(self):
        """
        Make sure pg_trgm extension, the file_name column and the GIN indexes exist.
        Call this from on_startup().
        """
        async with self.pool.acquire() as conn:
            # pg_trgm for fuzzy search
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            # column (harmless if it already exists)
            await conn.execute(
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS file_name TEXT NOT NULL DEFAULT ''")
            # fast substring / trigram search
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_files_name_trgm
                ON files USING GIN (file_name gin_trgm_ops)""")
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_subjects_name_trgm
                ON subjects USING GIN (name gin_trgm_ops)""")
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_teachers_name_trgm
                ON teachers USING GIN (name gin_trgm_ops)""")

    async def _day_bounds_utc(self, user_id: int, day: date):
        tz = await self.get_user_timezone(user_id)
        start_local = datetime.combine(day, time.min)
        end_local   = start_local + timedelta(days=1)
        return (tz.localize(start_local).astimezone(pytz.UTC),
                tz.localize(end_local).astimezone(pytz.UTC))

    async def add_user(self, user_id: int, timezone: str = None):
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    if timezone is None:
                        timezone = 'Asia/Tashkent'  # GMT+5 default
                    await conn.execute('''
                        INSERT INTO users (user_id, timezone)
                        VALUES ($1, $2)
                        ON CONFLICT (user_id) DO NOTHING
                    ''', user_id, timezone)
                    logger.info(f"Added/updated user {user_id} with timezone {timezone}")
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {str(e)}")
            raise

    async def get_all_users(self):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT user_id FROM users
                ''')
                return [row['user_id'] for row in rows]
        except Exception as e:
            logger.error(f"Error fetching all users: {str(e)}")
            return []

    async def get_user_timezone(self, user_id: int) -> pytz.timezone:
        try:
            async with self.pool.acquire() as conn:
                timezone_str = await conn.fetchval('''
                    SELECT timezone FROM users WHERE user_id = $1
                ''', user_id)
                if timezone_str:
                    return pytz.timezone(timezone_str)
                return self.default_timezone
        except Exception as e:
            logger.error(f"Error fetching timezone for user {user_id}: {str(e)}")
            return self.default_timezone
        
    async def set_user_timezone(self, user_id: int, timezone: str):
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('''
                        INSERT INTO users (user_id, timezone)
                        VALUES ($1, $2)
                        ON CONFLICT (user_id)
                        DO UPDATE SET timezone = $2
                    ''', user_id, timezone)
                    logger.info(f"Set timezone for user {user_id} to {timezone}")
        except Exception as e:
            logger.error(f"Error setting timezone for user {user_id}: {str(e)}")
            raise

    # Schedule functions
    async def add_event(self, user_id: int, event: str, event_datetime: datetime):
        await self.add_user(user_id)
        if event_datetime.tzinfo is None:
            user_timezone = await self.get_user_timezone(user_id)
            event_datetime = user_timezone.localize(event_datetime)
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('''
                        INSERT INTO schedules (user_id, event, event_datetime)
                        VALUES ($1, $2, $3)
                    ''', user_id, event, event_datetime)
                    logger.info(f"Added event '{event}' for user {user_id} at {event_datetime}")
        except Exception as e:
            logger.error(f"Error adding event for user {user_id}: {str(e)}")
            raise

    async def get_schedule(self, user_id: int, day: str):
        day_obj = datetime.strptime(day, "%Y-%m-%d").date()
        start_utc, end_utc = await self._day_bounds_utc(user_id, day_obj)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT event, event_datetime
                    FROM schedules
                    WHERE user_id = $1
                    AND event_datetime >= $2
                    AND event_datetime <  $3
                ORDER BY event_datetime''',
                user_id, start_utc, end_utc
            )
        tz = await self.get_user_timezone(user_id)
        return [(r['event'], r['event_datetime'].astimezone(tz).strftime('%H:%M'))
                for r in rows]


    async def get_all_schedules(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, event, event_datetime
                    FROM schedules
                    WHERE user_id = $1
                    ORDER BY event_datetime
                ''', user_id)

                user_timezone = await self.get_user_timezone(user_id)
                return [
                    (
                        row['id'],
                        row['event'],
                        row['event_datetime'].astimezone(user_timezone).strftime('%Y-%m-%d'),
                        row['event_datetime'].astimezone(user_timezone).strftime('%H:%M'),
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error fetching schedules for user {user_id}: {str(e)}")
            return []
        
    async def get_user_future_schedules(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT event, event_datetime FROM schedules
                    WHERE user_id = $1 AND event_datetime > NOW()
                ''', user_id)
                return rows
        except Exception as e:
            logger.error(f"Error fetching future schedules for user {user_id}: {str(e)}")
            return []
        
    async def get_due_schedules(self, user_id: int, now_local: datetime):
        start_local = now_local.replace(second=0, microsecond=0)
        end_local   = start_local + timedelta(minutes=1)
        start_utc   = start_local.astimezone(pytz.UTC)
        end_utc     = end_local.astimezone(pytz.UTC)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT id, event, event_datetime
                FROM schedules
                WHERE user_id = $1
                AND reminded = FALSE
                AND event_datetime >= $2 AND event_datetime < $3''',
                user_id, start_utc, end_utc
            )
        return [(r['id'], r['event'], r['event_datetime']) for r in rows]

    async def mark_schedule_reminded(self, schedule_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE schedules SET reminded = TRUE WHERE id = $1", schedule_id)

    async def update_schedule(self, schedule_id: int, event: str, event_datetime: datetime):
        if event_datetime.tzinfo is None:
            # Fetch user_id from schedule to get correct timezone
            async with self.pool.acquire() as conn:
                user_id = await conn.fetchval('''
                    SELECT user_id FROM schedules WHERE id = $1
                ''', schedule_id)
                if user_id:
                    user_timezone = await self.get_user_timezone(user_id)
                    event_datetime = user_timezone.localize(event_datetime)
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('''
                        UPDATE schedules
                        SET event = $1, event_datetime = $2
                        WHERE id = $3
                    ''', event, event_datetime, schedule_id)
                    logger.info(f"Updated schedule {schedule_id}")
        except Exception as e:
            logger.error(f"Error updating schedule {schedule_id}: {str(e)}")
            raise

    async def delete_schedule(self, schedule_id: int):
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute('DELETE FROM schedules WHERE id = $1', schedule_id)
                    logger.info(f"Deleted schedule {schedule_id}")
        except Exception as e:
            logger.error(f"Error deleting schedule {schedule_id}: {str(e)}")
            raise

    # Task functions
    async def add_task(self, user_id: int, task: str, deadline: datetime, category: str):
        await self.add_user(user_id)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO tasks (user_id, task, deadline, category)
                    VALUES ($1, $2, $3, $4)
                ''', user_id, task, deadline, category)
                logger.info(f"Added task '{task}' for user {user_id} with deadline {deadline}")
        except Exception as e:
            logger.error(f"Error adding task for user {user_id}: {str(e)}")
            raise

    async def get_tasks_due_now(self, user_id: int, now_local: datetime):
        start_local = now_local.replace(second=0, microsecond=0)
        end_local   = start_local + timedelta(minutes=1)
        start_utc   = start_local.astimezone(pytz.UTC)
        end_utc     = end_local.astimezone(pytz.UTC)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT id, task, deadline, category
                    FROM tasks
                    WHERE user_id  = $1
                    AND reminded = FALSE
                    AND deadline >= $2
                    AND deadline <  $3''',
                user_id, start_utc, end_utc
            )
        return [(r['id'], r['task'], r['deadline'], r['category']) for r in rows]


    async def mark_task_reminded(self, task_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET reminded = TRUE WHERE id = $1",
                task_id,
            )

    async def get_tasks(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT task, deadline, category FROM tasks
                    WHERE user_id = $1
                    ORDER BY deadline
                ''', user_id)
                return [(row['task'], row['deadline'], row['category']) for row in rows]
        except Exception as e:
            logger.error(f"Error getting tasks for user {user_id}: {str(e)}")
            raise

    async def get_tasks_by_deadline(self, user_id: int, day: date):
        start_utc, end_utc = await self._day_bounds_utc(user_id, day)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT task, deadline, category
                    FROM tasks
                    WHERE user_id  = $1
                    AND deadline >= $2
                    AND deadline <  $3
                ORDER BY deadline''',
                user_id, start_utc, end_utc
            )
        return [(r['task'], r['deadline'], r['category']) for r in rows]

    async def get_all_tasks(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, task, deadline, category
                    FROM tasks
                    WHERE user_id = $1
                ''', user_id)
                return [(row['id'], row['task'], row['deadline'], row['category']) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching tasks for user {user_id}: {str(e)}")
            return []

    async def update_task(self, task_id: int, task: str, deadline: datetime, category: str):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE tasks
                    SET task = $1, deadline = $2, category = $3
                    WHERE id = $4
                ''', task, deadline, category, task_id)
                logger.info(f"Updated task {task_id}")
        except Exception as e:
            logger.error(f"Error updating task {task_id}: {str(e)}")
            raise

    async def delete_task(self, task_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('DELETE FROM tasks WHERE id = $1', task_id)
                logger.info(f"Deleted task {task_id}")
        except Exception as e:
            logger.error(f"Error deleting task {task_id}: {str(e)}")
            raise

    # File functions
    async def add_file(
        self,
        user_id: int,
        telegram_file_id: str,
        file_name: str,
        subject_id: int | None,
        description: str,
    ):
        await self.add_user(user_id)
        async with self.pool.acquire() as conn:
               row = await conn.fetchrow('''
        INSERT INTO files (user_id, telegram_file_id, subject_id,
                           description, file_name, upload_date)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    ''',
        user_id, telegram_file_id, subject_id, description,
        file_name, datetime.now())
        logger.info("Added file %s for user %s", row["id"], user_id)
        return row["id"]

    async def get_files_with_teachers(self, user_id: int):
        """
        Return tuples:
            (telegram_file_id, subject, teacher_names, description, file_id)

        – Includes files that have *no subject* or whose subject has *no teachers*.
        – Teacher names are comma‑separated and alphabetically ordered.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    f.id,
                    f.telegram_file_id,
                    s.name AS subject,                                         -- may be NULL
                    COALESCE(
                        NULLIF( string_agg(DISTINCT t.name, ', ' ORDER BY t.name), '' ),
                        'No teacher'
                    ) AS teacher_names,
                    f.description
                FROM files AS f
                LEFT JOIN subjects          AS s  ON f.subject_id = s.id
                LEFT JOIN subject_teachers  AS st ON s.id        = st.subject_id
                LEFT JOIN teachers          AS t  ON st.teacher_id = t.id
                WHERE f.user_id = $1
                GROUP BY f.id, s.name, f.description
                ORDER BY f.upload_date DESC
                """,
                user_id,
            )

        return [
            (
                row["telegram_file_id"],
                row["subject"],
                row["teacher_names"],
                row["description"],
                row["id"],
            )
            for row in rows
        ]

    async def update_file(self, user_id: int, file_id: int, subject_id: int = None, description: str = None, telegram_file_id: str = None):
        try:
            async with self.pool.acquire() as conn:
                if subject_id is not None:
                    await conn.execute('''
                        UPDATE files
                        SET subject_id = $1
                        WHERE id = $2 AND user_id = $3
                    ''', subject_id, file_id, user_id)
                if description:
                    await conn.execute('''
                        UPDATE files
                        SET description = $1
                        WHERE id = $2 AND user_id = $3
                    ''', description, file_id, user_id)
                if telegram_file_id:
                    await conn.execute('''
                        UPDATE files
                        SET telegram_file_id = $1
                        WHERE id = $2 AND user_id = $3
                    ''', telegram_file_id, file_id, user_id)
                logger.info(f"Updated file {file_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Error updating file {file_id} for user {user_id}: {str(e)}")
            raise

    async def delete_file(self, user_id: int, file_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('DELETE FROM files WHERE id = $1 AND user_id = $2', file_id, user_id)
                logger.info(f"Deleted file {file_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting file {file_id} for user {user_id}: {str(e)}")
            raise

    # Subject functions

    # Count how many files are uploaded by a user and linked to this teacher (via subject)
    async def count_files_by_teacher(self, user_id: int, teacher_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COUNT(DISTINCT f.id)
                FROM files f
                JOIN subjects s ON f.subject_id = s.id
                JOIN subject_teachers st ON s.id = st.subject_id
                WHERE f.user_id = $1 AND st.teacher_id = $2
            """, user_id, teacher_id)

    # Count files linked directly to a subject
    async def count_files_by_subject(self, user_id: int, subject_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*)
                FROM files
                WHERE user_id = $1 AND subject_id = $2
            """, user_id, subject_id)

    async def add_subject(self, user_id: int, name: str):
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    INSERT INTO subjects (user_id, name) VALUES ($1, $2) RETURNING id
                ''', user_id, name)
                logger.info(f"Added subject {row['id']} for user {user_id}")
                return row['id']
        except Exception as e:
            logger.error(f"Error adding subject for user {user_id}: {str(e)}")
            raise

    async def get_subjects(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, name FROM subjects WHERE user_id = $1 ORDER BY name
                ''', user_id)
                return [(row['id'], row['name']) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subjects for user {user_id}: {str(e)}")
            raise

    async def update_subject(self, user_id: int, subject_id: int, new_name: str):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE subjects
                    SET name = $1
                    WHERE id = $2 AND user_id = $3
                ''', new_name, subject_id, user_id)
                logger.info("Renamed subject %s → %s for user %s",
                            subject_id, new_name, user_id)
        except Exception as e:
            logger.error("Error renaming subject %s: %s", subject_id, e)
            raise

    async def delete_subject(self, user_id: int, subject_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    DELETE FROM subjects
                    WHERE id = $1 AND user_id = $2
                ''', subject_id, user_id)
                logger.info("Deleted subject %s for user %s", subject_id, user_id)
        except Exception as e:
            logger.error("Error deleting subject %s: %s", subject_id, e)
            raise

    # Teacher functions
    async def add_teacher(self, user_id: int, name: str):
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    INSERT INTO teachers (user_id, name) VALUES ($1, $2) RETURNING id
                ''', user_id, name)
                logger.info(f"Added teacher {row['id']} for user {user_id}")
                return row['id']
        except Exception as e:
            logger.error(f"Error adding teacher for user {user_id}: {str(e)}")
            raise

    async def get_teachers(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, name FROM teachers WHERE user_id = $1 ORDER BY name
                ''', user_id)
                return [(row['id'], row['name']) for row in rows]
        except Exception as e:
            logger.error(f"Error getting teachers for user {user_id}: {str(e)}")
            raise

    async def update_teacher(self, user_id: int, teacher_id: int, new_name: str):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE teachers
                    SET name = $1
                    WHERE id = $2 AND user_id = $3
                ''', new_name, teacher_id, user_id)
                logger.info("Renamed teacher %s → %s for user %s",
                            teacher_id, new_name, user_id)
        except Exception as e:
            logger.error("Error renaming teacher %s: %s", teacher_id, e)
            raise

    async def delete_teacher(self, user_id: int, teacher_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    DELETE FROM teachers
                    WHERE id = $1 AND user_id = $2
                ''', teacher_id, user_id)
                logger.info("Deleted teacher %s for user %s", teacher_id, user_id)
        except Exception as e:
            logger.error("Error deleting teacher %s: %s", teacher_id, e)
            raise

    # Subject-Teacher relationship functions
    async def assign_teacher_to_subject(self, subject_id: int, teacher_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO subject_teachers (subject_id, teacher_id) VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                ''', subject_id, teacher_id)
                logger.info(f"Assigned teacher {teacher_id} to subject {subject_id}")
        except Exception as e:
            logger.error(f"Error assigning teacher to subject: {str(e)}")
            raise

    async def get_teachers_for_subject(self, subject_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT t.id, t.name FROM teachers t
                    JOIN subject_teachers st ON t.id = st.teacher_id
                    WHERE st.subject_id = $1
                ''', subject_id)
                return [(row['id'], row['name']) for row in rows]
        except Exception as e:
            logger.error(f"Error getting teachers for subject {subject_id}: {str(e)}")
            raise

    async def get_teachers_page(self, user_id: int, page: int):
        """
        Return (rows, total_count) where `rows` is a list of (id, name)
        for the requested page (1‑based). Uses PAGE_SIZE = 5.
        """
        offset = (page - 1) * 5
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name
                FROM teachers
                WHERE user_id = $1
                ORDER BY id
                LIMIT $2 OFFSET $3
                """,
                user_id, 5, offset
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM teachers WHERE user_id = $1",
                user_id,
            )
        return [(r["id"], r["name"]) for r in rows], total


    async def get_subjects_page(self, user_id: int, page: int):
        """
        Same as get_teachers_page, but for subjects.
        """
        offset = (page - 1) * 5
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name
                FROM subjects
                WHERE user_id = $1
                ORDER BY id
                LIMIT $2 OFFSET $3
                """,
                user_id, 5, offset
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM subjects WHERE user_id = $1",
                user_id,
            )
        return [(r["id"], r["name"]) for r in rows], total

    async def get_teacher(self, user_id: int, teacher_id: int):
        """
        Return asyncpg.Record with (id, name) for a single teacher.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, name FROM teachers WHERE id = $1 AND user_id = $2",
                teacher_id, user_id
            )


    async def get_subject(self, user_id: int, subject_id: int):
        """
        Return asyncpg.Record with (id, name) for a single subject.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, name FROM subjects WHERE id = $1 AND user_id = $2",
                subject_id, user_id
            )

    # Search files
    async def search_files(self, user_id: int, keyword: str):
        """
        Returns two lists:
            hits         – exact/ILIKE matches first
            suggestions  – closest fuzzy‑matches when there were no hits
        Each list contains tuples:
            (telegram_file_id, subject, description, file_id)
        """
        try:
            kw = f"%{keyword}%"
            async with self.pool.acquire() as conn:
                # 1️⃣ exact / ILIKE search across all three dimensions
                rows = await conn.fetch("""
                    SELECT
                        f.id,
                        f.telegram_file_id,
                        COALESCE(s.name, '—') AS subject,
                        f.description
                    FROM files               f
                    LEFT JOIN subjects          s  ON f.subject_id = s.id
                    LEFT JOIN subject_teachers  st ON s.id         = st.subject_id
                    LEFT JOIN teachers          t  ON st.teacher_id = t.id
                    WHERE f.user_id = $1
                    AND (
                        f.file_name ILIKE $2
                        OR s.name      ILIKE $2
                        OR t.name      ILIKE $2
                    )
                    GROUP BY f.id, f.telegram_file_id, subject, f.description
                    ORDER BY MAX(f.upload_date) DESC        -- newest first
                """, user_id, kw)

                hits = [(r['telegram_file_id'], r['subject'], r['description'], r['id'])
                        for r in rows]

                # 2️⃣ if nothing found, offer the five closest by trigram similarity
                suggestions: list[tuple] = []
                if not hits:
                    rows = await conn.fetch("""
                        SELECT DISTINCT f.id, f.telegram_file_id,
                            COALESCE(s.name, '—') AS subject,
                            f.description,
                            GREATEST(
                                similarity(f.file_name, $2),
                                similarity(s.name,       $2),
                                similarity(t.name,       $2)
                            ) AS sim
                        FROM files f
                        LEFT JOIN subjects          s  ON f.subject_id = s.id
                        LEFT JOIN subject_teachers  st ON s.id       = st.subject_id
                        LEFT JOIN teachers          t  ON st.teacher_id = t.id
                        WHERE f.user_id = $1
                        ORDER BY sim DESC
                        LIMIT 5
                    """, user_id, keyword)
                    suggestions = [(r['telegram_file_id'], r['subject'],
                                    r['description'], r['id']) for r in rows]

            return hits, suggestions
        except Exception as e:
            logger.error(f"Error searching files for user {user_id}: {str(e)}")
            raise

    # Ticket functions
    async def add_ticket(self, user_id: int, subject: str, ticket: str):
        await self.add_user(user_id)
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    INSERT INTO tickets (user_id, subject, ticket)
                    VALUES ($1, $2, $3)
                    RETURNING id
                ''', user_id, subject, ticket)
                logger.info(f"Added ticket {row['id']} for user {user_id}")
                return row['id']
        except Exception as e:
            logger.error(f"Error adding ticket for user {user_id}: {str(e)}")
            raise

    async def get_tickets(self, user_id: int, subject: str):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, ticket FROM tickets
                    WHERE user_id = $1 AND subject = $2
                    ORDER BY id
                ''', user_id, subject)
                return [(row['id'], row['ticket']) for row in rows]
        except Exception as e:
            logger.error(f"Error getting tickets for user {user_id}: {str(e)}")
            raise

    async def get_all_tickets(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, subject, ticket FROM tickets
                    WHERE user_id = $1
                    ORDER BY subject, id
                ''', user_id)
                return [(row['id'], row['subject'], row['ticket']) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all tickets for user {user_id}: {str(e)}")
            raise

    async def get_ticket_subjects(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT DISTINCT subject FROM tickets
                    WHERE user_id = $1
                    ORDER BY subject
                ''', user_id)
                return [row['subject'] for row in rows]
        except Exception as e:
            logger.error(f"Error getting ticket subjects for user {user_id}: {str(e)}")
            raise

    async def update_ticket(self, ticket_id: int, ticket: str):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE tickets
                    SET ticket = $1
                    WHERE id = $2
                ''', ticket, ticket_id)
                logger.info(f"Updated ticket {ticket_id}")
        except Exception as e:
            logger.error(f"Error updating ticket {ticket_id}: {str(e)}")
            raise

    async def delete_ticket(self, ticket_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('DELETE FROM tickets WHERE id = $1', ticket_id)
                logger.info(f"Deleted ticket {ticket_id}")
        except Exception as e:
            logger.error(f"Error deleting ticket {ticket_id}: {str(e)}")
            raise

    async def delete_all_tickets(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('DELETE FROM tickets WHERE user_id = $1', user_id)
                logger.info(f"Deleted all tickets for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting all tickets for user {user_id}: {str(e)}")
            raise

    # Google token functions
    async def save_google_token(self, user_id: int, token_json: str):
        await self.add_user(user_id)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO google_tokens (user_id, token_json)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO UPDATE SET token_json = $2
                ''', user_id, token_json)
                logger.info(f"Saved Google token for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving Google token for user {user_id}: {str(e)}")
            raise

    async def get_google_token(self, user_id: int):
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('SELECT token_json FROM google_tokens WHERE user_id = $1', user_id)
                return row['token_json'] if row else None
        except Exception as e:
            logger.error(f"Error getting Google token for user {user_id}: {str(e)}")
            raise

    # Conversion log functions
    async def log_conversion(self, user_id: int, conversion_type: str):
        await self.add_user(user_id)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO conversions (user_id, conversion_type, timestamp)
                    VALUES ($1, $2, $3)
                ''', user_id, conversion_type, datetime.now())
                logger.info(f"Logged conversion {conversion_type} for user {user_id}")
        except Exception as e:
            logger.error(f"Error logging conversion for user {user_id}: {str(e)}")
            raise

    async def close_pool(self):
            if self.pool:
                await self.pool.close()
                logger.info("Database connection pool closed")

    async def get_upcoming_events(self, user_id: int, now: datetime):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT event, event_datetime 
                    FROM schedules
                    WHERE user_id = $1 
                    AND event_datetime BETWEEN $2 AND $2 + INTERVAL '1 hour'
                    ORDER BY event_datetime
                ''', user_id, now)
                return rows
        except Exception as e:
            logger.error(f"Error fetching schedules for user {user_id}: {str(e)}")
            return []
        
     # -- email prefs ------------------------------------------------------------
    async def set_user_email(self, user_id: int, email: str):
        await self.pool.execute(
            "UPDATE users SET email=$2 WHERE user_id=$1", user_id, email.lower()
        )

    async def set_email_enabled(self, user_id: int, enabled: bool):
        await self.pool.execute(
            "UPDATE users SET email_enabled=$2 WHERE user_id=$1", user_id, enabled
        )

    async def get_email_prefs(self, user_id: int) -> tuple[str | None, bool]:
        row = await self.pool.fetchrow(
            "SELECT email, email_enabled FROM users WHERE user_id=$1",
            user_id
        )
        return (row["email"], row["email_enabled"]) if row else (None, False)
    
    async def get_reminder_settings(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('''
                SELECT pre_event_offset_minutes, daily_reminder_enabled, daily_reminder_time,
                    email, email_enabled
                FROM users WHERE user_id = $1
            ''', user_id)

    async def update_reminder_setting(self, user_id: int, key: str, value):
        async with self.pool.acquire() as conn:
            await conn.execute(f'''
                UPDATE users SET {key} = $1 WHERE user_id = $2
            ''', value, user_id)


db = Database()