from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.exceptions import MessageNotModified
import math
from loader import bot, dp
from database.db import db
from states.forms import AddTeacherForm, AddSubjectForm, RenameTeacherForm, RenameSubjectForm


PAGE_SIZE = 5

# ─── helper: remember list‑message chat & id in per‑user storage ─
async def _store_list_message(chat_id: int, msg_id: int, user_id: int):
    await dp.current_state(chat=chat_id, user=user_id).update_data(
        list_chat=chat_id,
        list_msg=msg_id,
    )

async def _get_list_message(user_id: int, chat_id: int):
    data = await dp.current_state(chat=chat_id, user=user_id).get_data()
    return data.get("list_chat"), data.get("list_msg")

# ────────────────────────────────────────────────────────────────
#  Rendering helpers (ONE source of truth)
# ────────────────────────────────────────────────────────────────
async def render_teachers_page(chat_id: int, msg_id: int,
                               user_id: int, page: int):
    rows, total = await db.get_teachers_page(user_id, page)
    pages = max(1, math.ceil(total / PAGE_SIZE))

    text = f"👥 <b>Your teachers</b>  (page {page}/{pages})\n\n"
    kb   = InlineKeyboardMarkup(row_width=1)

    try:
        await bot.edit_message_text(
            text, chat_id, msg_id,
            reply_markup=kb, parse_mode="HTML"
        )
    except MessageNotModified:
        pass

    for tid, name in rows:
        kb.add(InlineKeyboardButton(
            name, callback_data=f"mgr:T:open:{tid}:p{page}"
        ))
        text += f"• {name}\n"

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"mgr:T:p{page-1}"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"mgr:T:p{page+1}"))
    if nav:
        kb.row(*nav)

    
    kb.row(
        InlineKeyboardButton("➕ Add", callback_data=f"mgr:T:add:p{page}"),
        InlineKeyboardButton("🏠 Home", callback_data="mgr:root")
    )

    await bot.edit_message_text(
        text, chat_id, msg_id,
        reply_markup=kb, parse_mode="HTML"
    )


async def render_subjects_page(chat_id: int, msg_id: int,
                               user_id: int, page: int):
    rows, total = await db.get_subjects_page(user_id, page)
    pages = max(1, math.ceil(total / PAGE_SIZE))

    text = f"📚 <b>Your subjects</b>  (page {page}/{pages})\n\n"
    kb   = InlineKeyboardMarkup(row_width=1)

    try:
        await bot.edit_message_text(
            text, chat_id, msg_id,
            reply_markup=kb, parse_mode="HTML"
        )
    except MessageNotModified:
        pass

    for sid, name in rows:
        kb.add(InlineKeyboardButton(
            name, callback_data=f"mgr:S:open:{sid}:p{page}"
        ))
        text += f"• {name}\n"

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"mgr:S:p{page-1}"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"mgr:S:p{page+1}"))
    if nav:
        kb.row(*nav)

    kb.row(
        InlineKeyboardButton("➕ Add", callback_data=f"mgr:S:add:p{page}"),
        InlineKeyboardButton("🏠 Home", callback_data="mgr:root")
    )

    await bot.edit_message_text(
        text, chat_id, msg_id,
        reply_markup=kb, parse_mode="HTML"
    )

# ────────────────────────────────────────────────────────────────
#  Root chooser
# ────────────────────────────────────────────────────────────────
async def mgr_root(chat_id: int, msg_id: int | None = None, user_id: int = None):
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("👥 Teachers", callback_data="mgr:T:p1"),
        InlineKeyboardButton("📚 Subjects", callback_data="mgr:S:p1"),
    )

    if msg_id:   # edit existing
        await bot.edit_message_text("📂 Choose what you want to manage:",
                                    chat_id, msg_id, reply_markup=kb)
    else:        # new message
        msg = await bot.send_message(chat_id, "📂 Choose what you want to manage:",
                                     reply_markup=kb)
        msg_id = msg.message_id
        if user_id:
            await _store_list_message(chat_id, msg_id, user_id)

# opened from main menu
@dp.message_handler(lambda m: m.text == "👨‍🏫 Subjects & Teachers")
async def open_manager_from_menu(m: types.Message):
    await mgr_root(m.chat.id, user_id=m.from_user.id)

# Home button
@dp.callback_query_handler(lambda c: c.data == "mgr:root")
async def mgr_root_cb(c: CallbackQuery):
    await mgr_root(c.message.chat.id, c.message.message_id)
    await c.answer()

# ────────────────────────────────────────────────────────────────
#  List‑page callbacks (T:p<n> / S:p<n>)
# ────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:T:p") or
                                      c.data.startswith("mgr:S:p"))
async def mgr_list_page_cb(c: CallbackQuery):
    _, scope, page_token = c.data.split(":")
    page = int(page_token[1:])

    if scope == "T":
        await render_teachers_page(c.message.chat.id, c.message.message_id,
                                   c.from_user.id, page)
    else:
        await render_subjects_page(c.message.chat.id, c.message.message_id,
                                   c.from_user.id, page)
    await c.answer()

# ────────────────────────────────────────────────────────────────
#  Add items
# ────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:T:add"))
async def add_teacher_start(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[3][1:])
    await state.update_data(return_page=page)
    await AddTeacherForm.name.set()
    await bot.send_message(c.from_user.id, "Enter new teacher name:")
    await c.answer()

@dp.message_handler(state=AddTeacherForm.name)
async def add_teacher_save(m: types.Message, state: FSMContext):
    data = await state.get_data()
    page = data["return_page"]
    await db.add_teacher(m.from_user.id, m.text.strip())
    await m.reply("Teacher added ✅")
    await state.finish()

    chat_id, msg_id = await _get_list_message(m.from_user.id, m.chat.id)
    await render_teachers_page(chat_id, msg_id, m.from_user.id, page)

# same for subjects
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:S:add"))
async def add_subject_start(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[3][1:])
    await state.update_data(return_page=page)
    await AddSubjectForm.name.set()
    await bot.send_message(c.from_user.id, "Enter new subject name:")
    await c.answer()

@dp.message_handler(state=AddSubjectForm.name)
async def add_subject_save(m: types.Message, state: FSMContext):
    data = await state.get_data()
    page = data["return_page"]
    await db.add_subject(m.from_user.id, m.text.strip())
    await m.reply("Subject added ✅")
    await state.finish()

    chat_id, msg_id = await _get_list_message(m.from_user.id, m.chat.id)
    await render_subjects_page(chat_id, msg_id, m.from_user.id, page)

# ────────────────────────────────────────────────────────────────
#  Open card view
# ────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:T:open") or
                                      c.data.startswith("mgr:S:open"))
async def mgr_open_card(c: CallbackQuery):
    scope, _, rid, page_str = c.data.split(":")[1:]
    rid  = int(rid)
    page = int(page_str[1:])
    user_id = c.from_user.id

    if scope == "T":
        row = await db.get_teacher(user_id, rid)
        subjects = await db.get_subjects(user_id)
        assigned = [
            sname for sid, sname in subjects
            if (await db.get_teachers_for_subject(sid)) and rid in [tid for tid, _ in await db.get_teachers_for_subject(sid)]
        ]
        file_count = await db.count_files_by_teacher(user_id, rid)
        header = (
            f"👩‍🏫 <b>{row['name']}</b>\n\n"
            f"📚 Subjects: {', '.join(assigned) if assigned else '—'}\n"
            f"📁 Files: {file_count}"
        )
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("📚 Assign to subject", callback_data=f"mgr:T:assign:{rid}"),
            InlineKeyboardButton("✏️ Rename",            callback_data=f"mgr:T:rename:{rid}:p{page}"),
            InlineKeyboardButton("🗑️ Delete",            callback_data=f"mgr:T:del:{rid}:p{page}"),
            InlineKeyboardButton("🔙 Back",              callback_data=f"mgr:T:p{page}")
        )
    else:
        row = await db.get_subject(user_id, rid)
        teachers = await db.get_teachers_for_subject(rid)
        file_count = await db.count_files_by_subject(user_id, rid)
        header = (
            f"📚 <b>{row['name']}</b>\n\n"
            f"👥 Teachers: {', '.join(t[1] for t in teachers) if teachers else '—'}\n"
            f"📁 Files: {file_count}"
        )
        kb = InlineKeyboardMarkup(row_width=1).add(
        
            InlineKeyboardButton("👥 Assign teacher", callback_data=f"mgr:S:assign:{rid}"),
            InlineKeyboardButton("✏️ Rename",         callback_data=f"mgr:S:rename:{rid}:p{page}"),
            InlineKeyboardButton("🗑️ Delete",         callback_data=f"mgr:S:del:{rid}:p{page}"),
            InlineKeyboardButton("🔙 Back",           callback_data=f"mgr:S:p{page}")
        )

    await bot.edit_message_text(header, c.message.chat.id, c.message.message_id,
                                reply_markup=kb, parse_mode="HTML")
    await c.answer()

# ────────────────────────────────────────────────────────────────
#  Rename
# ────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:T:rename"))
async def rename_teacher_start(c: CallbackQuery, state: FSMContext):
    _, _, _, tid, page_str = c.data.split(":")
    await state.update_data(tid=int(tid), return_page=int(page_str[1:]))
    await RenameTeacherForm.new_name.set()
    await bot.send_message(c.from_user.id, "Send new teacher name:")
    await c.answer()

@dp.message_handler(state=RenameTeacherForm.new_name)
async def rename_teacher_save(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await db.update_teacher(m.from_user.id, data["tid"], m.text.strip())
    await m.reply("Renamed ✅")
    await state.finish()

    chat_id, msg_id = await _get_list_message(m.from_user.id, m.chat.id)
    await render_teachers_page(chat_id, msg_id, m.from_user.id, data["return_page"])

# rename subject
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:S:rename"))
async def rename_subject_start(c: CallbackQuery, state: FSMContext):
    _, _, _, sid, page_str = c.data.split(":")
    await state.update_data(sid=int(sid), return_page=int(page_str[1:]))
    await RenameSubjectForm.new_name.set()
    await bot.send_message(c.from_user.id, "Send new subject name:")
    await c.answer()

@dp.message_handler(state=RenameSubjectForm.new_name)
async def rename_subject_save(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await db.update_subject(m.from_user.id, data["sid"], m.text.strip())
    await m.reply("Renamed ✅")
    await state.finish()

    chat_id, msg_id = await _get_list_message(m.from_user.id, m.chat.id)
    await render_subjects_page(chat_id, msg_id, m.from_user.id, data["return_page"])

# ────────────────────────────────────────────────────────────────
#  Delete
# ────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:T:del"))
async def del_teacher(c: CallbackQuery):
    _, _, _, tid, page_str = c.data.split(":")
    await db.delete_teacher(c.from_user.id, int(tid))
    chat_id, msg_id = await _get_list_message(c.from_user.id, c.message.chat.id)
    await render_teachers_page(chat_id, msg_id, c.from_user.id, int(page_str[1:]))
    await c.answer("Deleted ✅")

@dp.callback_query_handler(lambda c: c.data.startswith("mgr:S:del"))
async def del_subject(c: CallbackQuery):
    _, _, _, sid, page_str = c.data.split(":")
    await db.delete_subject(c.from_user.id, int(sid))
    chat_id, msg_id = await _get_list_message(c.from_user.id, c.message.chat.id)
    await render_subjects_page(chat_id, msg_id, c.from_user.id, int(page_str[1:]))
    await c.answer("Deleted ✅")

# ────────────────────────────────────────────────────────────────
#  Assign flows
# ────────────────────────────────────────────────────────────────
@dp.callback_query_handler(lambda c: c.data.startswith("mgr:T:assign"))
async def assign_teacher_pick_subject(c: CallbackQuery):
    tid = int(c.data.split(":")[3])
    subjects = await db.get_subjects(c.from_user.id)
    kb = InlineKeyboardMarkup(row_width=1)
    for sid, name in subjects:
        kb.add(InlineKeyboardButton(name, callback_data=f"mgr:link:T:{tid}:{sid}"))
    kb.add(InlineKeyboardButton("✖️ Cancel", callback_data="mgr:root"))
    await bot.edit_message_text("Choose subject to assign:", c.message.chat.id,
                                c.message.message_id, reply_markup=kb)
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("mgr:S:assign"))
async def assign_subject_pick_teacher(c: CallbackQuery):
    sid = int(c.data.split(":")[3])
    teachers = await db.get_teachers(c.from_user.id)
    kb = InlineKeyboardMarkup(row_width=1)
    for tid, name in teachers:
        kb.add(InlineKeyboardButton(name, callback_data=f"mgr:link:S:{sid}:{tid}"))
    kb.add(InlineKeyboardButton("✖️ Cancel", callback_data="mgr:root"))
    await bot.edit_message_text("Choose teacher to assign:", c.message.chat.id,
                                c.message.message_id, reply_markup=kb)
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("mgr:link:T"))
async def link_teacher_subject(c: CallbackQuery):
    _, _, _, tid, sid = c.data.split(":")
    await db.assign_teacher_to_subject(int(sid), int(tid))
    await c.answer("Assigned ✅")
    await mgr_root(c.message.chat.id, c.message.message_id)

@dp.callback_query_handler(lambda c: c.data.startswith("mgr:link:S"))
async def link_subject_teacher(c: CallbackQuery):
    _, _, _, sid, tid = c.data.split(":")
    await db.assign_teacher_to_subject(int(sid), int(tid))
    await c.answer("Assigned ✅")
    await mgr_root(c.message.chat.id, c.message.message_id)