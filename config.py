import os
import pytz

OPENAI_API_KEY=os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv('BOT_TOKEN')
WEBHOOK_PATH = '/webhook'
BOT_TIMEZONE = pytz.timezone(os.getenv('BOT_TIMEZONE', 'Asia/Tashkent'))


SMTP_CFG = {
    "hostname": os.getenv("SMTP_HOST"),
    "port": int(os.getenv("SMTP_PORT", 587)),
    "username": os.getenv("SMTP_USER"),
    "password": os.getenv("SMTP_PASS"),
    "tls": os.getenv("SMTP_TLS", "true").lower() == "true",
}