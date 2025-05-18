from aiogram import types
from aiogram.dispatcher import FSMContext
from loader import dp, logger
from states.forms import GradeForm


@dp.message_handler(state=GradeForm.grades)
async def process_grades(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    grades_input = message.text.strip()
    logger.info(f"User {user_id} entered grades '{grades_input}'")
    try:
        if not grades_input:
            await message.reply("Grades cannot be empty! Enter numbers separated by spaces or use /cancel.")
            return
        grades = [float(g) for g in grades_input.split()]
        if not grades:
            await message.reply("No valid numbers found! Enter numbers like '5 4 3' or use /cancel.")
            return
        average = sum(grades) / len(grades)
        await message.reply(f"Average grade: {average:.2f}")
        await state.finish()
    except ValueError:
        await message.reply("Invalid grades! Enter numbers separated by spaces (e.g., 5 4 3) or use /cancel.")
    except Exception as e:
        logger.error(f"Error in process_grades for user {user_id}: {str(e)}")
        await message.reply("Error calculating grades!")
        await state.finish()
