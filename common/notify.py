"""Best-effort notifications: never let a blocked/missing chat crash a handler."""

import logging

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


async def notify(bot, tg_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await bot.send_message(chat_id=tg_id, text=text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramError as e:
        logger.warning("Could not notify %s: %s", tg_id, e)


async def notify_photo(bot, tg_id: int, photo_path: str, caption: str = "") -> None:
    try:
        with open(photo_path, "rb") as f:
            await bot.send_photo(chat_id=tg_id, photo=f, caption=caption, parse_mode="HTML")
    except TelegramError as e:
        logger.warning("Could not send photo to %s: %s", tg_id, e)
