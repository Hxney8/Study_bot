import logging
from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from openai import AsyncOpenAI
from config import BOT_TOKEN, OPENAI_API_KEY

# ─── Logging Setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("studybot")

# ─── Core Instances ──────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())
scheduler = AsyncIOScheduler()

# ─── External Services ───────────────────────────────────────────────────────
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
