import os
import asyncio
import subprocess
from io import BytesIO
from datetime import datetime

import fitz
from pdf2docx import Converter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile

from loader import bot, dp, logger
from states.forms import ConvertForm
from database.db import db


# ─── Show conversion options ─────────────────────────────────────────
async def show_converter_menu(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("PDF to Word", callback_data="pdf_to_word"),
        InlineKeyboardButton("PDF to TXT", callback_data="pdf_to_txt"),
        InlineKeyboardButton("Word to PDF", callback_data="word_to_pdf"),
        InlineKeyboardButton("PowerPoint to PDF", callback_data="ppt_to_pdf"),
        InlineKeyboardButton("Images to PDF", callback_data="images_to_pdf"),
    )
    await message.reply("Choose the conversion type:", reply_markup=kb)


# ─── ConvertForm: select conversion type ─────────────────────────────
@dp.callback_query_handler(lambda c: c.data in ["pdf_to_word", "pdf_to_txt", "word_to_pdf", "ppt_to_pdf", "images_to_pdf"], state=ConvertForm.select_type)
async def process_conversion_type(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    conversion_type = callback_query.data
    logger.info(f"User {user_id} selected conversion_type '{conversion_type}'")

    await state.update_data(conversion_type=conversion_type)
    await bot.answer_callback_query(callback_query.id)

    if conversion_type == "images_to_pdf":
        await ConvertForm.images.set()
        await bot.send_message(user_id, "Send images (as photos or documents). Type /done when finished.")
    else:
        await ConvertForm.file.set()
        await bot.send_message(user_id, "Send the file to convert.")


# ─── ConvertForm: PDF, Word, PPT ─────────────────────────────────────
@dp.message_handler(content_types=['document'], state=ConvertForm.file)
async def process_convert_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()

    conversion_type = data.get('conversion_type')
    if not conversion_type:
        await ConvertForm.select_type.set()
        return await show_converter_menu(message)

    file = message.document
    file_info = await bot.get_file(file.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    temp_dir = "/tmp/convert"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # PDF → Word / TXT
        if conversion_type in ["pdf_to_word", "pdf_to_txt"]:
            if file.mime_type != 'application/pdf':
                return await message.reply("Please send a PDF file.")

            pdf_path = os.path.join(temp_dir, "input.pdf")
            with open(pdf_path, "wb") as f:
                f.write(downloaded_file.read())

            if conversion_type == "pdf_to_txt":
                doc = fitz.open(pdf_path)
                text = "".join(p.get_text() for p in doc)
                doc.close()
                txt_file = BytesIO(text.encode("utf-8"))
                return await bot.send_document(message.chat.id, InputFile(txt_file, "converted.txt"), caption="Converted to TXT")
            else:
                docx_path = os.path.join(temp_dir, "converted.docx")
                await _pdf_to_docx(pdf_path, docx_path)
                return await bot.send_document(message.chat.id, InputFile(docx_path, "converted.docx"), caption="Converted to Word")

        # Word → PDF
        elif conversion_type == "word_to_pdf":
            if file.mime_type != 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                return await message.reply("Please send a Word (.docx) file.")

            docx_path = os.path.join(temp_dir, "input.docx")
            with open(docx_path, "wb") as f:
                f.write(downloaded_file.read())

            await asyncio.to_thread(
                subprocess.run,
                ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", temp_dir, docx_path],
                check=True,
            )

            pdf_path = docx_path.replace(".docx", ".pdf")
            return await bot.send_document(message.chat.id, InputFile(pdf_path, "converted.pdf"), caption="Converted to PDF")

        # PPT → PDF
        elif conversion_type == "ppt_to_pdf":
            if file.mime_type != 'application/vnd.openxmlformats-officedocument.presentationml.presentation':
                return await message.reply("Please send a PowerPoint (.pptx) file.")

            ppt_path = os.path.join(temp_dir, "input.pptx")
            with open(ppt_path, "wb") as f:
                f.write(downloaded_file.read())

            await asyncio.to_thread(
                subprocess.run,
                ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", temp_dir, ppt_path],
                check=True,
            )

            pdf_path = ppt_path.replace(".pptx", ".pdf")
            return await bot.send_document(message.chat.id, InputFile(pdf_path, "converted.pdf"), caption="Converted to PDF")

        await db.log_conversion(user_id, conversion_type)
        logger.info(f"User {user_id} completed {conversion_type} conversion")
    except Exception as e:
        logger.error(f"Conversion error for user {user_id}: {e}")
        await message.reply(f"Conversion error: {e}")
    finally:
        await state.finish()


# ─── ConvertForm: Image → PDF ────────────────────────────────────────
@dp.message_handler(content_types=['photo', 'document'], state=ConvertForm.images)
async def process_image(message: types.Message, state: FSMContext):
    data = await state.get_data()
    images = data.get('images', [])

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    images.append(file_id)

    await state.update_data(images=images)
    await message.reply("Image received. Send more or type /done.")


@dp.message_handler(commands=['done'], state=ConvertForm.images)
async def process_done_images(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    images = data.get('images', [])

    if not images:
        return await message.reply("No images received.")

    try:
        pdf_file = BytesIO()
        c = canvas.Canvas(pdf_file, pagesize=letter)
        for file_id in images:
            file_info = await bot.get_file(file_id)
            file_data = await bot.download_file(file_info.file_path)
            img = ImageReader(BytesIO(file_data.read()))
            c.drawImage(img, 0, 0, width=letter[0], height=letter[1], preserveAspectRatio=True)
            c.showPage()
        c.save()
        pdf_file.seek(0)

        await bot.send_document(message.chat.id, InputFile(pdf_file, "images.pdf"), caption="Converted to PDF")
        await db.log_conversion(user_id, "images_to_pdf")
    except Exception as e:
        logger.error(f"Image to PDF error: {e}")
        await message.reply(f"Image to PDF conversion failed: {e}")
    finally:
        await state.finish()


# ─── ConvertForm: Invalid image input ───────────────────────────────
@dp.message_handler(state=ConvertForm.images)
async def process_invalid_images(message: types.Message, state: FSMContext):
    await message.reply("Please send images or type /done.")


# ─── Utility: PDF to DOCX async wrapper ──────────────────────────────
async def _pdf_to_docx(pdf_path: str, docx_path: str):
    def _convert():
        cv = Converter(pdf_path)
        cv.convert(docx_path, start=0, end=None)
        cv.close()
    await asyncio.to_thread(_convert)
