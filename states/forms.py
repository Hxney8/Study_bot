from aiogram.dispatcher.filters.state import State, StatesGroup

# FSM states
class ScheduleForm(StatesGroup):
    event       = State()
    date        = State()
    date_manual = State()
    time        = State()
    time_manual = State()
    edit_id     = State()


class TaskForm(StatesGroup):
    task            = State()
    deadline        = State()
    deadline_manual = State()
    time            = State()
    time_manual     = State()
    category        = State()


class FileForm(StatesGroup):
    select_subject = State()
    description = State()
    file = State()


class FileUpdateForm(StatesGroup):
    select_field = State()
    subject = State()
    description = State()
    file = State()


class GradeForm(StatesGroup):
    grades = State()


class ConvertForm(StatesGroup):
    select_type = State()
    file = State()
    images = State()


class TicketForm(StatesGroup):
    subject = State()
    topics = State()
    generate = State()
    edit_id = State()
    edit_text = State()


class AddTeacherForm(StatesGroup):
    name = State()

class RenameTeacherForm(StatesGroup):
    teacher_id = State()
    new_name   = State()

class AddSubjectForm(StatesGroup):
    name = State()

class RenameSubjectForm(StatesGroup):
    subject_id = State()
    new_name   = State()

class SearchForm(StatesGroup):
    select_method = State()


class SetTimezoneForm(StatesGroup):
    timezone = State()


class EmailForm(StatesGroup):
    waiting_email = State()


class ReminderForm(StatesGroup):
    waiting_offset = State()
    waiting_daily_time = State()