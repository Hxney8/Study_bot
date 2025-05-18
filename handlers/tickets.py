import random
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from loader import bot, dp, logger, openai_client
from database.db import db
from states.forms import TicketForm


async def show_ticket_menu(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Add Tickets", callback_data="add_tickets"),
        InlineKeyboardButton("📂 View Tickets", callback_data="view_tickets"),
        InlineKeyboardButton("✏️ Edit Tickets", callback_data="edit_tickets"),
        InlineKeyboardButton("🎲 Random Ticket", callback_data="random_ticket"),
        InlineKeyboardButton("🗑 Delete All", callback_data="delete_all_tickets"),
    )
    await message.reply("🎲 Ticket Generator Menu:", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "add_tickets")
async def process_add_tickets(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'add_tickets'")
    await TicketForm.subject.set()
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(user_id, "Enter the subject (e.g., History):")
    logger.info(f"User {user_id} moved to TicketForm:subject")

@dp.message_handler(state=TicketForm.subject)
async def process_ticket_subject(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    subject = message.text.strip()
    logger.info(f"User {user_id} entered subject '{subject}'")
    try:
        if not subject:
            await message.reply("Subject cannot be empty! Try again or use /cancel.")
            return
        async with state.proxy() as data:
            data['subject'] = subject
        await TicketForm.topics.set()
        await message.reply("Enter topics separated by commas (e.g., Medieval, Modern) or leave empty:")
    except Exception as e:
        logger.error(f"Error in process_ticket_subject for user {user_id}: {str(e)}")
        await message.reply("Error!")
        await state.finish()

@dp.message_handler(state=TicketForm.topics)
async def process_topics(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    topics_input = message.text.strip()
    logger.info(f"User {user_id} entered topics '{topics_input}'")
    try:
        topics = [t.strip() for t in topics_input.split(',') if t.strip()] if topics_input else []
        async with state.proxy() as data:
            data['topics'] = topics
        await TicketForm.generate.set()
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("Generate with AI", callback_data="generate_ai"))
        keyboard.add(InlineKeyboardButton("Enter manually", callback_data="generate_manual"))
        await message.reply("How to add tickets?", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in process_topics for user {user_id}: {str(e)}")
        await message.reply("Error!")
        await state.finish()

@dp.callback_query_handler(lambda c: c.data == "generate_ai", state=TicketForm.generate)
async def process_generate_ai(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'generate_ai'")
    async with state.proxy() as data:
        subject = data['subject']
        topics = data.get('topics', [])
    try:
        topics_str = ", ".join(topics) if topics else "any relevant topics for university students"
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates exam questions for university students."},
                {"role": "user", "content": f"Generate 5 exam questions for the subject '{subject}' covering {topics_str}. Format as a numbered list."}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        tickets = response.choices[0].message.content.split('\n')
        tickets = [t.strip() for t in tickets if t.strip() and t.strip().startswith(('1.', '2.', '3.', '4.', '5.'))]
        tickets = [t.lstrip('0123456789. ').strip() for t in tickets]
        if not tickets:
            await bot.send_message(user_id, "Failed to generate tickets. Try again or enter manually.")
            await state.finish()
            return
        ticket_ids = []
        for ticket in tickets:
            ticket_id = await db.add_ticket(user_id, subject, ticket)
            ticket_ids.append((ticket_id, ticket))
        response = f"Added {len(tickets)} tickets for {subject}:\n"
        for i, (_, ticket) in enumerate(ticket_ids, 1):
            response += f"{i}. {ticket}\n"
        await bot.send_message(user_id, response)
    except Exception as e:
        logger.error(f"AI generation error for user {user_id}: {str(e)}")
        await bot.send_message(user_id, f"Generation error: {str(e)}")
    await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "generate_manual", state=TicketForm.generate)
async def process_generate_manual(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'generate_manual'")
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(user_id, "Enter the list of tickets/questions, one per line (or leave empty to skip):")
    await TicketForm.generate.set()

@dp.message_handler(state=TicketForm.generate)
async def process_tickets(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    tickets_input = message.text.strip()
    logger.info(f"User {user_id} entered tickets '{tickets_input}'")
    try:
        async with state.proxy() as data:
            subject = data['subject']
        tickets = [t.strip() for t in tickets_input.split('\n') if t.strip()]
        if not tickets:
            await message.reply("No tickets provided! Try again or use /cancel.")
            return
        ticket_ids = []
        for ticket in tickets:
            ticket_id = await db.add_ticket(user_id, subject, ticket)
            ticket_ids.append((ticket_id, ticket))
        response = f"Added {len(tickets)} tickets for {subject}:\n"
        for i, (_, ticket) in enumerate(ticket_ids, 1):
            response += f"{i}. {ticket}\n"
        await message.reply(response)
        await state.finish()
    except Exception as e:
        logger.error(f"Error in process_tickets for user {user_id}: {str(e)}")
        await message.reply("Error saving tickets!")
        await state.finish()

@dp.callback_query_handler(lambda c: c.data == "view_tickets")
async def process_view_tickets(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'view_tickets'")
    try:
        subjects = await db.get_ticket_subjects(user_id)
        if not subjects:
            await bot.send_message(user_id, "No tickets added yet!")
        else:
            keyboard = InlineKeyboardMarkup()
            for subject in subjects:
                keyboard.add(InlineKeyboardButton(subject, callback_data=f"view_subject_{subject}"))
            await bot.send_message(user_id, "Choose a subject to view tickets:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error viewing tickets for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading tickets!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("view_subject_"))
async def process_view_subject_tickets(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    subject = callback_query.data.replace("view_subject_", "")
    logger.info(f"User {user_id} viewing tickets for subject '{subject}'")
    try:
        tickets = await db.get_tickets(user_id, subject)
        if tickets:
            response = f"Tickets for {subject}:\n"
            for i, (_, ticket) in enumerate(tickets, 1):
                response += f"{i}. {ticket}\n"
        else:
            response = f"No tickets for {subject}!"
        await bot.send_message(user_id, response)
    except Exception as e:
        logger.error(f"Error viewing subject tickets for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading tickets!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "edit_tickets")
async def process_edit_tickets(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'edit_tickets'")
    try:
        tickets = await db.get_all_tickets(user_id)
        if not tickets:
            await bot.send_message(user_id, "No tickets added yet!")
        else:
            keyboard = InlineKeyboardMarkup(row_width=1)
            for ticket_id, subject, ticket in tickets:
                keyboard.add(InlineKeyboardButton(
                    f"{subject}: {ticket[:30]}...", callback_data=f"ticket_{ticket_id}"
                ))
            await bot.send_message(user_id, "Choose a ticket to edit/delete:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in process_edit_tickets for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error loading tickets!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("ticket_"))
async def process_ticket_action(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    ticket_id = int(callback_query.data.replace("ticket_", ""))
    logger.info(f"User {user_id} selected ticket {ticket_id}")
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Edit", callback_data=f"edit_ticket_{ticket_id}"))
    keyboard.add(InlineKeyboardButton("Delete", callback_data=f"delete_ticket_{ticket_id}"))
    await bot.send_message(user_id, "What to do with the ticket?", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith("edit_ticket_"))
async def process_edit_ticket_form(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    ticket_id = int(callback_query.data.replace("edit_ticket_", ""))
    logger.info(f"User {user_id} editing ticket {ticket_id}")
    try:
        async with state.proxy() as data:
            data['edit_id'] = ticket_id
        await TicketForm.edit_text.set()
        await bot.send_message(user_id, "Enter the new ticket text:")
    except Exception as e:
        logger.error(f"Error in process_edit_ticket_form for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error editing ticket!")
        await state.finish()
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=TicketForm.edit_text)
async def process_edit_ticket_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    ticket_text = message.text.strip()
    logger.info(f"User {user_id} entered ticket text '{ticket_text}'")
    try:
        async with state.proxy() as data:
            ticket_id = data['edit_id']
        if not ticket_text:
            await message.reply("Ticket text cannot be empty! Try again or use /cancel.")
            return
        await db.update_ticket(ticket_id, ticket_text)
        await message.reply("Ticket updated!")
        await state.finish()
    except Exception as e:
        logger.error(f"Error in process_edit_ticket_text for user {user_id}: {str(e)}")
        await message.reply("Error updating ticket!")
        await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("delete_ticket_"))
async def process_delete_ticket(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    ticket_id = int(callback_query.data.replace("delete_ticket_", ""))
    logger.info(f"User {user_id} deleting ticket {ticket_id}")
    try:
        await db.delete_ticket(ticket_id)
        await bot.send_message(user_id, "Ticket deleted!")
    except Exception as e:
        logger.error(f"Error deleting ticket for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error deleting ticket!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "delete_all_tickets")
async def process_delete_all_tickets(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'delete_all_tickets'")
    try:
        await db.delete_all_tickets(user_id)
        await bot.send_message(user_id, "All tickets deleted!")
    except Exception as e:
        logger.error(f"Error deleting all tickets for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error deleting tickets!")
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == "random_ticket")
async def process_random_ticket(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'random_ticket'")
    try:
        tickets = await db.get_all_tickets(user_id)
        if not tickets:
            await bot.send_message(user_id, "No tickets available!")
        else:
            ticket_id, subject, ticket = random.choice(tickets)
            await bot.send_message(user_id, f"Random ticket for {subject}:\n{ticket}")
    except Exception as e:
        logger.error(f"Error selecting random ticket for user {user_id}: {str(e)}")
        await bot.send_message(user_id, "Error selecting ticket!")
    await bot.answer_callback_query(callback_query.id)