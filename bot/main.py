import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import bank, company
from .scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# "awaiting" keys owned by the bank flows; everything else (including no
# awaiting state at all, and registration) is handled by the company module.
BANK_AWAITING_KEYS = {"deposit_custom_amount", "transfer_custom_amount"}


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    awaiting = context.user_data.get("awaiting")
    if awaiting in BANK_AWAITING_KEYS:
        await bank.on_text(update, context)
    else:
        await company.on_text(update, context)


def main() -> None:
    load_dotenv()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set (see .env.example)")

    async def post_init(app: Application) -> None:
        setup_scheduler(app)

    application = Application.builder().token(token).post_init(post_init).build()

    application.add_handler(CommandHandler("start", company.cmd_start))
    application.add_handler(CallbackQueryHandler(company.on_callback_registration, pattern=r"^reg:role:"))
    application.add_handler(CallbackQueryHandler(company.on_callback, pattern=r"^co:"))
    application.add_handler(CallbackQueryHandler(bank.on_callback, pattern=r"^bank:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("МикРоб bot starting...")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
