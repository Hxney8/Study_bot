import ssl
import traceback
import email.message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib

from config import SMTP_CFG
from loader import logger


async def send_email(
    to_addr: str,
    subject: str,
    body: str,
    content_type: str = "text/html",
    plain_text: str | None = None
):
    """
    Sends an email (HTML or plain) via SMTP using aiosmtplib.

    Args:
        to_addr: Email recipient
        subject: Email subject line
        body: Main HTML or plain content
        content_type: "text/html" or "text/plain"
        plain_text: Optional fallback for clients that don’t support HTML
    """
    try:
        # Basic plain fallback
        if plain_text is None:
            plain_text = (
                f"{subject}\n\n"
                "Please view this email in an HTML-compatible client.\n"
                "Alternatively, check your StudyBot interface for full content."
            )

        # Build message based on content type
        if content_type == "text/html":
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(plain_text, "plain", "utf-8"))
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg = email.message.EmailMessage()
            msg.set_content(plain_text, subtype="plain", charset="utf-8")

        msg["From"] = SMTP_CFG["username"]
        msg["To"] = to_addr
        msg["Subject"] = subject

        # Send via secure SMTP
        ssl_ctx = ssl.create_default_context()
        await aiosmtplib.send(
            msg,
            hostname=SMTP_CFG["hostname"],
            port=SMTP_CFG["port"],
            username=SMTP_CFG["username"],
            password=SMTP_CFG["password"],
            start_tls=SMTP_CFG["tls"],
            tls_context=ssl_ctx,
            timeout=15,
        )
        logger.info("Email sent to %s: %s", to_addr, subject)
        return True

    except Exception as e:
        logger.error("Failed to send email to %s: %s\n%s", to_addr, e, traceback.format_exc())
        return False


