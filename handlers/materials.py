from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.db import db
from loader import bot, dp, logger
from states.forms import SearchForm, FileForm, FileUpdateForm

FILES_PER_PAGE = 5

# --- Materials Menu ---
async def materials_menu(message: types.Message, state: FSMContext):
    """Handle the Materials menu selection and show files."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} selected 'Materials', current state: {await state.get_state()}")
    await state.finish()
    await show_files(user_id)

async def show_files(user_id: int, page: int = 1):
    try:
        files = await db.get_files_with_teachers(user_id)
        if not files:
            keyboard = InlineKeyboardMarkup(row_width=2)
            keyboard.add(InlineKeyboardButton("➕ Upload File", callback_data="upload_file"))
            keyboard.add(InlineKeyboardButton("🔍 Search Files", callback_data="search_files"))
            await bot.send_message(user_id, "No files found. Upload or search:", reply_markup=keyboard)
            return

        total_pages = (len(files) + FILES_PER_PAGE - 1) // FILES_PER_PAGE
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * FILES_PER_PAGE
        end_idx = start_idx + FILES_PER_PAGE
        files_page = files[start_idx:end_idx]

        for telegram_file_id, subject, teacher_names, description, file_id in files_page:
            try:
                # Skip if not a valid document file ID (Telegram documents usually start with 'BQAC')
                if not telegram_file_id or not telegram_file_id.startswith("BQAC"):
                    continue

                subject_label = subject or "No subject"
                teacher_label = teacher_names or "No teacher"

                file_keyboard = InlineKeyboardMarkup(row_width=2)
                file_keyboard.add(
                    InlineKeyboardButton("✏️ Update", callback_data=f"update_file_{file_id}"),
                    InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_file_{file_id}")
                )

                caption = f"📚 {subject_label}\n👨‍🏫 {teacher_label}\n📝 {description or '—'}"
                await bot.send_document(user_id, telegram_file_id, caption=caption, reply_markup=file_keyboard)
            except Exception as file_err:
                logger.error(f"Error sending file_id {file_id} for user {user_id}: {file_err}")
                continue

        nav_keyboard = InlineKeyboardMarkup(row_width=3)
        if page > 1:
            nav_keyboard.insert(InlineKeyboardButton("⬅️ Prev", callback_data=f"materials_page_{page-1}"))
        nav_keyboard.insert(InlineKeyboardButton("➕ Upload File", callback_data="upload_file"))
        nav_keyboard.insert(InlineKeyboardButton("🔍 Search Files", callback_data="search_files"))
        if page < total_pages:
            nav_keyboard.insert(InlineKeyboardButton("Next ➡️", callback_data=f"materials_page_{page+1}"))

        await bot.send_message(user_id, f"Page {page}/{total_pages}", reply_markup=nav_keyboard)
    except Exception as e:
        logger.error(f"Error showing files for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading files!")




@dp.callback_query_handler(lambda c: c.data.startswith("materials_page_"))
async def materials_page_navigation(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    page = int(callback_query.data.split("_")[-1])
    logger.info(f"User {user_id} navigating to materials page {page}")
    await bot.answer_callback_query(callback_query.id)
    await show_files(user_id, page=page)


# ---------------------------------------------------------------------------
# UPLOAD NEW FILE FLOW  (with optional subject)
# ---------------------------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data == "upload_file")
async def process_upload_file(callback_query: CallbackQuery, state: FSMContext):
    """First step: show subject list or let the user skip tagging."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'upload_file'")
    try:
        subjects = await db.get_subjects(user_id)
        keyboard = InlineKeyboardMarkup()
        if subjects:
            for subject_id, name in subjects:
                keyboard.add(InlineKeyboardButton(name, callback_data=f"select_subject_{subject_id}"))
        # Always allow skipping – handy when the user has zero subjects, too.
        keyboard.add(InlineKeyboardButton("➖ Skip", callback_data="select_subject_skip"))
        await bot.send_message(user_id, "Select a subject for the file (or skip):", reply_markup=keyboard)
        await FileForm.select_subject.set()
    except Exception as e:
        logger.error(f"Error listing subjects for file upload for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error listing subjects!")
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(
    lambda c: c.data.startswith("select_subject_") or c.data == "select_subject_skip",
    state=FileForm.select_subject
)
async def process_select_subject_for_file(callback_query: CallbackQuery, state: FSMContext):
    """Handle concrete subject choice *or* the skip action."""
    user_id = callback_query.from_user.id
    data_payload = callback_query.data.replace("select_subject_", "")
    logger.info(f"User {user_id} selected subject payload '{data_payload}'")

    if data_payload == "skip":
        subject_id = None
    else:
        subject_id = int(data_payload)

    await state.update_data(subject_id=subject_id)
    await FileForm.description.set()
    await bot.send_message(user_id, "Enter the description:")
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(state=FileForm.description)
async def process_file_description(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    description = message.text.strip()
    logger.info(f"User {user_id} entered description '{description}'")
    if not description:
        await message.reply("❗ Description cannot be empty. Try again:")
        return

    await state.update_data(description=description)
    await FileForm.file.set()
    await message.reply("Send the file (document, photo, etc.):")


@dp.message_handler(content_types=["document", "photo"], state=FileForm.file)
async def process_file_upload(message: types.Message, state: FSMContext):
    """Save the file, including a human‑readable file_name, then refresh Materials."""
    user_id = message.from_user.id
    logger.info("User %s uploaded file", user_id)

    try:
        data = await state.get_data()
        telegram_file_id = (
            message.document.file_id
            if message.document else message.photo[-1].file_id
        )
        # may be None when the user chose “Skip”
        subject_id   = data.get("subject_id")
        description  = data["description"]

        # Decide what to store as file_name (becomes searchable later)
        if message.document and message.document.file_name:
            file_name = message.document.file_name
        if message.photo:
            await message.reply("❌ Please upload using the 📎 *File* option, not as a photo.")
            return
        else:
            file_name = "unnamed"

        # (user_id, telegram_file_id, file_name, subject_id, description)
        await db.add_file(user_id, telegram_file_id,
                          file_name, subject_id, description)

        await message.reply("✅ File uploaded successfully!")
    except Exception as e:
        logger.error("Error uploading file for user %s: %s", user_id, e)
        await message.reply("❌ Error uploading file!")
    finally:
        await state.finish()
        await show_files(user_id, page=1)


@dp.message_handler(lambda message: message.content_type != types.ContentType.DOCUMENT, state=FileForm.file)
async def reject_invalid_file_upload(message: types.Message, state: FSMContext):
    ct = message.content_type

    if ct == types.ContentType.PHOTO:
        msg = "❌ You sent a *photo*.\nPlease upload files using the 📎 *File* option (PDF, DOCX, etc)."
    elif ct == types.ContentType.TEXT:
        msg = "❌ That’s text. Please send your study material as a file using the 📎 *File* button."
    elif ct == types.ContentType.VIDEO:
        msg = "❌ Video uploads aren't supported. Use the 📎 *File* option to send documents."
    else:
        msg = "❌ Unsupported file type.\nUse the 📎 *File* option to upload valid documents like PDF or Word."

    await message.reply(msg, parse_mode="Markdown")


# --- Update File Flow ---
@dp.callback_query_handler(lambda c: c.data.startswith("update_file_"))
async def update_file(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    file_id = int(callback_query.data.replace("update_file_", ""))
    logger.info(f"User {user_id} clicked 'update_file_{file_id}'")
    try:
        files = await db.get_files(user_id)
        file_data = next((f for f in files if f[3] == file_id), None)
        if not file_data:
            await bot.send_message(user_id, "File not found!")
            return
        await state.update_data(file_id=file_id)
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("Subject", callback_data="update_subject"),
            InlineKeyboardButton("Description", callback_data="update_description"),
            InlineKeyboardButton("File", callback_data="update_file")
        )
        await bot.send_message(user_id, "What would you like to update?", reply_markup=keyboard)
        await FileUpdateForm.select_field.set()
    except Exception as e:
        logger.error(f"Error initiating file update for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error starting update!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data in ["update_subject", "update_description", "update_file"], state=FileUpdateForm.select_field)
async def process_update_field(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    field = callback_query.data
    logger.info(f"User {user_id} selected update field '{field}'")
    try:
        await state.update_data(update_field=field)
        if field == "update_subject":
            subjects = await db.get_subjects(user_id)
            if not subjects:
                await bot.send_message(user_id, "You have no subjects! Add subjects first.")
                await state.finish()
                return
            keyboard = InlineKeyboardMarkup()
            for subject_id, name in subjects:
                keyboard.add(InlineKeyboardButton(name, callback_data=f"update_subject_{subject_id}"))
            await bot.send_message(user_id, "Select the new subject:", reply_markup=keyboard)
            await FileUpdateForm.subject.set()
        elif field == "update_description":
            await FileUpdateForm.description.set()
            await bot.send_message(user_id, "Enter the new description:")
        else:  # update_file
            await FileUpdateForm.file.set()
            await bot.send_message(user_id, "Send the new file (document or photo):")
    except Exception as e:
        logger.error(f"Error processing update field for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("update_subject_"), state=FileUpdateForm.subject)
async def process_update_subject_selection(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    subject_id = int(callback_query.data.replace("update_subject_", ""))
    logger.info(f"User {user_id} selected new subject ID {subject_id}")
    try:
        data = await state.get_data()
        file_id = data['file_id']
        await db.update_file(user_id, file_id, subject_id=subject_id)
        await bot.send_message(user_id, "✅ Subject updated successfully!")
        await state.finish()
        await show_files(user_id, page=1)
    except Exception as e:
        logger.error(f"Error updating subject for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error updating subject!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=FileUpdateForm.description)
async def process_update_description(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    description = message.text.strip()
    logger.info(f"User {user_id} entered new description '{description}'")
    try:
        if not description:
            await message.reply("❗ Description cannot be empty. Try again:")
            return
        data = await state.get_data()
        file_id = data['file_id']
        await db.update_file(user_id, file_id, description=description)
        await message.reply("✅ Description updated successfully!")
        await state.finish()
        await show_files(user_id, page=1)
    except Exception as e:
        logger.error(f"Error updating description for user {user_id}: {str(e)}")
        await message.reply("Error updating description!")
        await state.finish()

@dp.message_handler(content_types=['document', 'photo'], state=FileUpdateForm.file)
async def process_update_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    logger.info(f"User {user_id} uploaded new file")
    try:
        data = await state.get_data()
        file_id = message.document.file_id if message.document else message.photo[-1].file_id
        old_file_id = data['file_id']
        await db.update_file(user_id, old_file_id, telegram_file_id=file_id)
        await message.reply("✅ File updated successfully!")
        await state.finish()
        await show_files(user_id, page=1)
    except Exception as e:
        logger.error(f"Error updating file for user {user_id}: {str(e)}")
        await message.reply("Error updating file!")
        await state.finish()

@dp.message_handler(content_types=['text'], state=FileUpdateForm.file)
async def invalid_update_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    logger.warning(f"User {user_id} sent text instead of file")
    await message.reply("❗ Please send a document or photo, not text.")

# --- Search Files ---
@dp.callback_query_handler(lambda c: c.data == "search_files", state="*")
async def process_search_files(callback_query: types.CallbackQuery, state: FSMContext):
    """Show search options with subject buttons and allow text input for subject or teacher."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'search_files'")
    await state.finish()
    try:
        subjects = await db.get_subjects(user_id)
        keyboard = InlineKeyboardMarkup(row_width=2)
        for subject_id, name in subjects:
            keyboard.add(InlineKeyboardButton(name, callback_data=f"search_subject_{subject_id}"))
        await bot.send_message(
            user_id,
            "Select a subject or type a subject/teacher name to search files:",
            reply_markup=keyboard
        )
        await SearchForm.select_method.set()
    except Exception as e:
        logger.error(f"Error initiating search for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading subjects!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("search_subject_"), state=SearchForm.select_method)
async def process_search_subject(callback_query: types.CallbackQuery, state: FSMContext):
    """Search files by selected subject."""
    user_id = callback_query.from_user.id
    subject_id = int(callback_query.data.replace("search_subject_", ""))
    logger.info(f"User {user_id} searching by subject ID {subject_id}")
    try:
        subject_name = next((s[1] for s in await db.get_subjects(user_id) if s[0] == subject_id), None)
        if not subject_name:
            await bot.send_message(user_id, "Subject not found!")
            await state.finish()
            return
        files = await db.search_files(user_id, subject_name)
        if not files:
            await bot.send_message(user_id, f"No files found for '{subject_name}'.")
        else:
            for telegram_file_id, subject, description, file_id in files:
                subject_id = next((s[0] for s in await db.get_subjects(user_id) if s[1] == subject), None)
                teachers = await db.get_teachers_for_subject(subject_id) if subject_id else []
                teacher_names = ", ".join(t[1] for t in teachers) if teachers else "No teacher"
                caption = f"📚 {subject}\n👨‍🏫 {teacher_names}\n📝 {description}"
                await bot.send_document(user_id, telegram_file_id, caption=caption)
            await bot.send_message(user_id, f"Found {len(files)} file(s) for '{subject_name}'.")
        await state.finish()
    except Exception as e:
        logger.error(f"Error searching subject for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error searching files!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(content_types=['sticker', 'photo', 'document', 'video', 'voice', 'animation'], state=SearchForm.select_method)
async def handle_invalid_search_input(message: types.Message, state: FSMContext):
    """Handle invalid non-text inputs in search state."""
    user_id = message.from_user.id
    logger.warning(f"User {user_id} sent non-text input in SearchForm:select_method")
    await message.reply("Please type a subject or teacher name to search, or select a subject.")

@dp.message_handler(state=SearchForm.select_method)
async def process_search_input(message: types.Message, state: FSMContext):
    """
    Search by file‑name, subject, or teacher.
    Exact ILIKE hits first; if none, show up to five fuzzy suggestions.
    """
    user_id = message.from_user.id
    keyword = message.text.strip()
    logger.info("User %s entered search keyword '%s'", user_id, keyword)

    if not keyword:
        await message.reply("Please type something to search.")
        return

    try:
        hits, suggestions = await db.search_files(user_id, keyword)

        # Helper – renders the list of files the same way Materials does
        async def _send_file_batch(rows):
            for telegram_file_id, subject, description, file_id in rows:
                # We need teacher names for the caption
                subject_id = next(
                    (sid for sid, name in await db.get_subjects(user_id)
                     if name == subject or (subject == '—' and sid is None)),
                    None,
                )
                teachers = await db.get_teachers_for_subject(subject_id) \
                           if subject_id else []
                teacher_names = ", ".join(t[1] for t in teachers) if teachers else "No teacher"

                caption = (f"📚 {subject or 'No subject'}\n"
                           f"👨‍🏫 {teacher_names}\n"
                           f"📝 {description or '—'}")

                kb = InlineKeyboardMarkup(row_width=2)
                kb.add(
                    InlineKeyboardButton("✏️ Update", callback_data=f"update_file_{file_id}"),
                    InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_file_{file_id}")
                )

                await bot.send_document(
                    user_id,
                    telegram_file_id,
                    caption=caption,
                    reply_markup=kb
                )

        if hits:
            await _send_file_batch(hits)
            await message.reply(f"Found {len(hits)} file(s) for “{keyword}”.")
        elif suggestions:
            await message.reply(
                "No exact matches. Maybe you meant one of these:")
            await _send_file_batch(suggestions)
        else:
            await message.reply("Nothing matched your search. 😕")

    except Exception as e:
        logger.error("Error searching files for user %s: %s", user_id, e)
        await message.reply("❌ Error searching files!")
    finally:
        await state.finish()

# --- Delete File Flow ---
@dp.callback_query_handler(lambda c: c.data.startswith("delete_file_"))
async def delete_file(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    file_id = int(callback_query.data.replace("delete_file_", ""))
    logger.info(f"User {user_id} clicked 'delete_file_{file_id}'")
    try:
        files = await db.get_files(user_id)
        file_data = next((f for f in files if f[3] == file_id), None)
        if not file_data:
            await bot.send_message(user_id, "File not found!")
            return
        await state.update_data(file_id=file_id)
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("Yes", callback_data=f"confirm_delete_{file_id}"),
            InlineKeyboardButton("No", callback_data="cancel_delete")
        )
        await bot.send_message(user_id, f"Are you sure you want to delete '{file_data[1]}'?", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error initiating file deletion for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error starting deletion!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("confirm_delete_"))
async def confirm_delete_file(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    file_id = int(callback_query.data.replace("confirm_delete_", ""))
    logger.info(f"User {user_id} confirmed deletion of file {file_id}")
    try:
        await db.delete_file(user_id, file_id)
        await bot.send_message(user_id, "🗑️ File deleted successfully!")
        await state.finish()
        await show_files(user_id, page=1)
    except Exception as e:
        logger.error(f"Error deleting file for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error deleting file!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "cancel_delete")
async def cancel_delete_file(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} canceled file deletion")
    await bot.send_message(user_id, "Deletion canceled.")
    await state.finish()
    await show_files(user_id, page=1)
    await bot.answer_callback_query(callback_query.id)