import logging

from telegram import Update
from telegram.ext import ContextTypes

from common import db
from common.money import format_money
from common.notify import notify

from . import keyboards_bank as kb

logger = logging.getLogger(__name__)

HISTORY_PAGE_SIZE = 5
HISTORY_TOTAL = 20


def _parse_amount(text: str) -> float | None:
    text = text.strip().replace(" ", "").replace("₽", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    return round(value, 2)


def _tx_line(tx: dict, viewer_id: int) -> str:
    date = tx["created_at"][:10]
    labels = {
        "deposit_open": "Открытие вклада",
        "deposit_close": "Закрытие вклада",
        "deposit_interest": "Проценты по вкладу",
        "bank_transfer": "Перевод",
        "dividend": "Дивиденды",
        "profit": "Прибыль компании",
        "task_penalty": "Штраф за просрочку",
        "share_transfer": "Передача акций",
    }
    label = labels.get(tx["type"], tx["type"])
    amount = tx["amount"]
    sign = ""
    if tx["type"] == "bank_transfer":
        if tx.get("from_id") == viewer_id:
            sign, label = "-", f"Перевод для {tx.get('description', '')}".strip()
        else:
            sign, label = "+", f"Перевод от {tx.get('description', '')}".strip()
    elif tx["type"] in ("deposit_open",):
        sign = "-"
    elif tx["type"] in ("deposit_close", "deposit_interest", "dividend"):
        sign = "+"
    desc = f" — {tx['description']}" if tx.get("description") and tx["type"] not in ("bank_transfer",) else ""
    return f"{date} — {label} — {sign}{format_money(amount)}{desc}"


async def _require_user(query, context) -> dict | None:
    snapshot = db.load()
    user = db.get_user(snapshot, query.from_user.id)
    if user is None:
        await query.answer("Вы не зарегистрированы. Отправьте /start", show_alert=True)
        return None
    return user


async def show_main_menu(query) -> None:
    await query.edit_message_text(
        "🏦 <b>Банк микробиксов хехе</b>\n\nВыберите действие:",
        reply_markup=kb.main_menu(),
        parse_mode="HTML",
    )


async def show_account(query, user: dict) -> None:
    total = user["cash"] + user["deposit"]
    text = (
        "💰 <b>Мой счёт</b>\n\n"
        f"Наличные: {format_money(user['cash'])}\n"
        f"Вклад: {format_money(user['deposit'])}\n"
        f"<b>Итого: {format_money(total)}</b>"
    )
    await query.edit_message_text(text, reply_markup=kb.account_menu(), parse_mode="HTML")


async def show_deposit(query, user: dict) -> None:
    has_deposit = user["deposit"] > 0
    if has_deposit:
        rate = db.load()["settings"]["deposit_rate_annual"]
        text = (
            "💎 <b>Вклад</b>\n\n"
            f"Сумма вклада: {format_money(user['deposit'])}\n"
            f"Ставка: {rate * 100:.0f}% годовых (капитализация ежедневно)\n"
            f"Открыт: {user['deposit_opened_at'][:10] if user['deposit_opened_at'] else '-'}\n"
            f"Начислено процентов за текущий вклад: {format_money(user['deposit_interest_accrued'])}"
        )
    else:
        text = "💎 <b>Вклад</b>\n\nУ вас пока нет открытого вклада. Ставка — 10% годовых, капитализация ежедневно."
    await query.edit_message_text(text, reply_markup=kb.deposit_menu(has_deposit), parse_mode="HTML")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    parts = data.split(":")
    # parts[0] == "bank"
    action = parts[1] if len(parts) > 1 else ""

    user = await _require_user(query, context)
    if user is None:
        return
    await query.answer()
    tg_id = user["tg_id"]

    if action == "menu":
        context.user_data.clear()
        await show_main_menu(query)
        return

    if action == "cancel":
        context.user_data.clear()
        await show_main_menu(query)
        return

    if action == "help":
        await query.edit_message_text(
            "ℹ️ <b>Помощь</b>\n\n"
            "💰 Мой счёт — баланс наличных и вклада\n"
            "💎 Вклад — открыть/закрыть вклад под 10% годовых\n"
            "💸 Перевод — перевести микробиксы другому пользователю\n"
            "📜 История — последние операции по счёту\n\n"
            "Кредиты и овердрафт не предусмотрены: баланс не может уйти в минус.",
            reply_markup=kb.back_to_menu(),
            parse_mode="HTML",
        )
        return

    if action == "account":
        await show_account(query, user)
        return

    if action == "deposit" and len(parts) == 2:
        await show_deposit(query, user)
        return

    if action == "deposit" and parts[2] == "open":
        context.user_data["flow"] = "deposit_open"
        await query.edit_message_text(
            "💎 На какую сумму открыть вклад?",
            reply_markup=kb.amount_picker("bank:dep"),
        )
        return

    if action == "deposit" and parts[2] == "close":
        if user["deposit"] <= 0:
            await query.answer("У вас нет открытого вклада", show_alert=True)
            return
        await query.edit_message_text(
            f"Закрыть вклад на сумму {format_money(user['deposit'])}? Деньги вернутся на счёт.",
            reply_markup=kb.confirm_cancel("bank:dep:close:confirm"),
        )
        return

    if action == "dep" and len(parts) >= 3 and parts[2] == "close" and parts[3] == "confirm":
        with db.transaction() as data:
            u = db.get_user(data, tg_id)
            amount = round(u["deposit"], 2)
            u["cash"] = round(u["cash"] + amount, 2)
            u["deposit"] = 0.0
            u["deposit_opened_at"] = None
            u["deposit_interest_accrued"] = 0.0
            u["deposit_last_capitalized_at"] = None
            db.add_transaction(data, "deposit_close", amount, to_id=tg_id, description="Закрытие вклада")
        context.user_data.clear()
        await query.edit_message_text(
            f"🔓 Вклад закрыт. На счёт зачислено {format_money(amount)}.",
            reply_markup=kb.back_to_menu(),
        )
        return

    if action == "deposit" and parts[2] == "stats":
        rate = db.load()["settings"]["deposit_rate_annual"]
        daily = user["deposit"] * rate / 365
        await query.edit_message_text(
            "📊 <b>Статистика по вкладу</b>\n\n"
            f"Тело вклада: {format_money(user['deposit'])}\n"
            f"Открыт: {user['deposit_opened_at'][:10] if user['deposit_opened_at'] else '-'}\n"
            f"Начислено процентов: {format_money(user['deposit_interest_accrued'])}\n"
            f"Ожидаемое начисление завтра: {format_money(daily)}",
            reply_markup=kb.back_to_menu(),
            parse_mode="HTML",
        )
        return

    if action == "dep" and len(parts) >= 3 and parts[2] == "amt":
        if parts[3] == "custom":
            context.user_data["awaiting"] = "deposit_custom_amount"
            await query.edit_message_text("✏️ Введите сумму вклада числом (в рублях):")
            return
        amount = float(parts[3])
        if amount > user["cash"]:
            await query.answer("Недостаточно средств на счёте", show_alert=True)
            return
        context.user_data["pending_amount"] = amount
        await query.edit_message_text(
            f"Открыть вклад на {format_money(amount)}?",
            reply_markup=kb.confirm_cancel(f"bank:dep:confirm:{amount}"),
        )
        return

    if action == "dep" and len(parts) >= 3 and parts[2] == "confirm":
        amount = float(parts[3])
        with db.transaction() as data:
            u = db.get_user(data, tg_id)
            if amount > u["cash"]:
                await query.answer("Недостаточно средств", show_alert=True)
                return
            u["cash"] = round(u["cash"] - amount, 2)
            u["deposit"] = round(u["deposit"] + amount, 2)
            u["deposit_opened_at"] = db.now_iso()
            u["deposit_interest_accrued"] = 0.0
            u["deposit_last_capitalized_at"] = db.today_str()
            db.add_transaction(data, "deposit_open", amount, from_id=tg_id, description="Открытие вклада")
        context.user_data.clear()
        await query.edit_message_text(
            f"💎 Вклад на {format_money(amount)} открыт! Ставка 10% годовых, капитализация ежедневно.",
            reply_markup=kb.back_to_menu(),
        )
        return

    if action == "transfer" and len(parts) == 2:
        snapshot = db.load()
        others = db.other_users(snapshot, tg_id)
        if not others:
            await query.edit_message_text("Пока нет других зарегистрированных пользователей.", reply_markup=kb.back_to_menu())
            return
        context.user_data["flow"] = "transfer"
        await query.edit_message_text("💸 Кому перевести?", reply_markup=kb.user_picker(others, "bank:tr"))
        return

    if action == "tr" and len(parts) >= 3 and parts[2] == "user":
        recipient_id = int(parts[3])
        context.user_data["transfer_to"] = recipient_id
        await query.edit_message_text("Введите сумму перевода:", reply_markup=kb.amount_picker("bank:tr"))
        return

    if action == "tr" and len(parts) >= 3 and parts[2] == "amt":
        recipient_id = context.user_data.get("transfer_to")
        if recipient_id is None:
            await query.answer("Начните перевод заново", show_alert=True)
            await show_main_menu(query)
            return
        if parts[3] == "custom":
            context.user_data["awaiting"] = "transfer_custom_amount"
            await query.edit_message_text("✏️ Введите сумму перевода числом (в рублях):")
            return
        amount = float(parts[3])
        if amount > user["cash"]:
            await query.answer("Недостаточно средств на счёте", show_alert=True)
            return
        recipient = db.get_user(db.load(), recipient_id)
        await query.edit_message_text(
            f"Перевести {format_money(amount)} пользователю {recipient['name']}?",
            reply_markup=kb.confirm_cancel(f"bank:tr:confirm:{amount}"),
        )
        return

    if action == "tr" and len(parts) >= 3 and parts[2] == "confirm":
        amount = float(parts[3])
        recipient_id = context.user_data.get("transfer_to")
        if recipient_id is None:
            await query.answer("Начните перевод заново", show_alert=True)
            await show_main_menu(query)
            return
        with db.transaction() as data:
            sender = db.get_user(data, tg_id)
            recipient = db.get_user(data, recipient_id)
            if recipient is None:
                await query.answer("Получатель не найден", show_alert=True)
                return
            if amount > sender["cash"]:
                await query.answer("Недостаточно средств", show_alert=True)
                return
            sender["cash"] = round(sender["cash"] - amount, 2)
            recipient["cash"] = round(recipient["cash"] + amount, 2)
            db.add_transaction(
                data, "bank_transfer", amount, from_id=tg_id, to_id=recipient_id,
                description=recipient["name"],
            )
            recipient_name = recipient["name"]
            sender_name = sender["name"]
        context.user_data.clear()
        await query.edit_message_text(
            f"✅ Переведено {format_money(amount)} пользователю {recipient_name}.",
            reply_markup=kb.back_to_menu(),
        )
        await notify(
            context.bot, recipient_id,
            f"💸 Вам перевели {format_money(amount)} от {sender_name}.",
        )
        return

    if action == "history":
        page = int(parts[2]) if len(parts) > 2 else 0
        snapshot = db.load()
        txs = db.user_transactions(snapshot, tg_id)[:HISTORY_TOTAL]
        start, end = page * HISTORY_PAGE_SIZE, (page + 1) * HISTORY_PAGE_SIZE
        chunk = txs[start:end]
        if not chunk and page > 0:
            page = 0
            start, end = 0, HISTORY_PAGE_SIZE
            chunk = txs[start:end]
        if not chunk:
            text = "📜 <b>История операций</b>\n\nПока нет операций."
        else:
            lines = [_tx_line(tx, tg_id) for tx in chunk]
            text = "📜 <b>История операций</b>\n\n" + "\n".join(lines)
        has_more = end < len(txs)
        await query.edit_message_text(text, reply_markup=kb.history_nav(page, has_more), parse_mode="HTML")
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return
    tg_id = update.effective_user.id
    snapshot = db.load()
    user = db.get_user(snapshot, tg_id)
    if user is None:
        return

    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("Не получилось распознать сумму. Введите положительное число, например 1500.")
        return

    if awaiting == "deposit_custom_amount":
        if amount > user["cash"]:
            await update.message.reply_text(
                f"Недостаточно средств. На счёте {format_money(user['cash'])}.",
            )
            return
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(
            f"Открыть вклад на {format_money(amount)}?",
            reply_markup=kb.confirm_cancel(f"bank:dep:confirm:{amount}"),
        )
        return

    if awaiting == "transfer_custom_amount":
        recipient_id = context.user_data.get("transfer_to")
        if recipient_id is None:
            context.user_data.clear()
            await update.message.reply_text("Начните перевод заново: /start")
            return
        if amount > user["cash"]:
            await update.message.reply_text(
                f"Недостаточно средств. На счёте {format_money(user['cash'])}.",
            )
            return
        recipient = db.get_user(db.load(), recipient_id)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(
            f"Перевести {format_money(amount)} пользователю {recipient['name']}?",
            reply_markup=kb.confirm_cancel(f"bank:tr:confirm:{amount}"),
        )
        return
