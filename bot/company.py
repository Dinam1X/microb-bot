import logging
import os
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from common import db
from common.models import share_percentage, threshold_reached, vote_weights
from common.money import format_money, format_percent, format_shares
from common.notify import notify, notify_photo

from . import keyboards_company as kb
from .charts import render_price_chart

logger = logging.getLogger(__name__)

TASK_PAGE_SIZE = 5
VOTE_PAGE_SIZE = 5

DEADLINE_CODES = {
    "today": timedelta(hours=12),
    "tomorrow": timedelta(days=1),
    "3d": timedelta(days=3),
    "week": timedelta(days=7),
}


def _parse_number(text: str) -> float | None:
    text = text.strip().replace(" ", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    tg_id = update.effective_user.id
    snapshot = db.load()
    user = db.get_user(snapshot, tg_id)
    if user is not None:
        await update.message.reply_text(
            f"🏢 <b>ПАО МикРоб</b>\n\nПривет, {user['name']}! Выберите действие:",
            reply_markup=kb.main_menu(),
            parse_mode="HTML",
        )
        return
    context.user_data["awaiting"] = "register_name"
    await update.message.reply_text(
        "🏢 <b>ПАО МикРоб</b>\n\nВы ещё не зарегистрированы. Как вас зовут?"
    )


async def on_text_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle registration-related text input. Returns True if it consumed the message."""
    awaiting = context.user_data.get("awaiting")
    if awaiting == "register_name":
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("Имя не может быть пустым. Введите имя:")
            return True
        context.user_data["reg_name"] = name
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"Приятно познакомиться, {name}! Какая у вас роль?", reply_markup=kb.role_picker())
        return True

    if awaiting == "register_custom_role":
        role = update.message.text.strip()
        if not role:
            await update.message.reply_text("Роль не может быть пустой. Введите роль:")
            return True
        await _finish_registration(update, context, role)
        return True

    return False


async def _finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, role: str) -> None:
    tg_id = update.effective_user.id
    name = context.user_data.get("reg_name", update.effective_user.first_name or "Без имени")
    with db.transaction() as data:
        if db.get_user(data, tg_id) is not None:
            context.user_data.clear()
            await update.message.reply_text("Вы уже зарегистрированы.", reply_markup=kb.main_menu())
            return
        db.create_user(data, tg_id, name, role)
        shares = db.get_shares(data, tg_id)
    context.user_data.clear()
    bonus = f"\n🎉 Вам начислено {format_shares(shares)} акций (вы в числе первых двух участников)!" if shares else ""
    await update.message.reply_text(
        f"✅ Регистрация завершена! Роль: {role}. Стартовый баланс: 10 000 ₽.{bonus}\n\nВыберите действие:",
        reply_markup=kb.main_menu(),
    )


async def on_callback_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    role = query.data.split(":", 2)[2]
    if role == "Другое":
        context.user_data["awaiting"] = "register_custom_role"
        await query.edit_message_text("Введите название вашей роли:")
        return
    tg_id = query.from_user.id
    name = context.user_data.get("reg_name", query.from_user.first_name or "Без имени")
    with db.transaction() as data:
        if db.get_user(data, tg_id) is not None:
            context.user_data.clear()
            await query.edit_message_text("Вы уже зарегистрированы.", reply_markup=kb.main_menu())
            return
        db.create_user(data, tg_id, name, role)
        shares = db.get_shares(data, tg_id)
    context.user_data.clear()
    bonus = f"\n🎉 Вам начислено {format_shares(shares)} акций (вы в числе первых двух участников)!" if shares else ""
    await query.edit_message_text(
        f"✅ Регистрация завершена! Роль: {role}. Стартовый баланс: 10 000 ₽.{bonus}\n\nВыберите действие:",
        reply_markup=kb.main_menu(),
    )


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

async def _require_user(query) -> dict | None:
    snapshot = db.load()
    user = db.get_user(snapshot, query.from_user.id)
    if user is None:
        await query.answer("Сначала зарегистрируйтесь: /start", show_alert=True)
        return None
    return user


async def show_main_menu(query) -> None:
    await query.edit_message_text("🏢 <b>ПАО МикРоб</b>\n\nВыберите действие:", reply_markup=kb.main_menu(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

async def show_dashboard(query, user: dict) -> None:
    snapshot = db.load()
    company = db.get_company(snapshot)
    holders = db.shareholders(snapshot)
    open_tasks = [t for t in snapshot["tasks"] if t["status"] == "open"]
    my_shares = db.get_shares(snapshot, user["tg_id"])

    history = company["price_history"]
    change = 0.0
    if len(history) >= 2:
        prev = history[-2]["price"]
        if prev:
            change = (history[-1]["price"] - prev) / prev * 100
    arrow = "↑" if change > 0 else ("↓" if change < 0 else "→")

    top_lines = []
    for holder_user, amount in holders[:5]:
        pct = share_percentage(amount, company["total_shares"])
        top_lines.append(f"  {holder_user['name']}: {format_shares(amount)} ({format_percent(pct)})")
    top_text = "\n".join(top_lines) if top_lines else "  пока нет держателей"

    est_dividend = company["cash_reserve"] * snapshot["settings"]["dividend_rate"]

    text = (
        f"📊 <b>{company['name']} ({company['ticker']})</b>\n\n"
        f"Цена акции: {format_money(company['share_price'])} ({arrow} {format_percent(abs(change))})\n"
        f"Касса компании: {format_money(company['cash_reserve'])}\n"
        f"Акций всего: {format_shares(company['total_shares'])}\n\n"
        f"<b>Топ держателей:</b>\n{top_text}\n\n"
        f"Открытых заданий: {len(open_tasks)}\n"
        f"Ожидаемые дивиденды: {format_money(est_dividend)}\n\n"
        f"Ваша роль: {user['role']}\nВаш пакет: {format_shares(my_shares)} акций"
    )
    await query.edit_message_text(text, reply_markup=kb.dashboard_menu(), parse_mode="HTML")


async def show_price_chart(query, context) -> None:
    snapshot = db.load()
    company = db.get_company(snapshot)
    await query.answer("Строю график...")
    path = render_price_chart(company["price_history"], company["ticker"])
    with open(path, "rb") as f:
        await context.bot.send_photo(chat_id=query.from_user.id, photo=f, caption=f"📈 {company['ticker']} — цена акции")
    try:
        os.remove(path)
    except OSError:
        pass


async def show_dashboard_tx(query) -> None:
    snapshot = db.load()
    txs = db.company_transactions(snapshot)[:10]
    labels = {
        "profit": "Прибыль",
        "dividend": "Дивиденды",
        "share_transfer": "Передача акций",
        "task_penalty": "Штраф",
    }
    if not txs:
        text = "📜 <b>Транзакции компании</b>\n\nПока нет операций."
    else:
        lines = [f"{tx['created_at'][:10]} — {labels.get(tx['type'], tx['type'])} — {format_money(tx['amount'])}" for tx in txs]
        text = "📜 <b>Транзакции компании</b>\n\n" + "\n".join(lines)
    await query.edit_message_text(text, reply_markup=kb.dashboard_menu(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------

async def show_shares(query, user: dict) -> None:
    snapshot = db.load()
    company = db.get_company(snapshot)
    amount = db.get_shares(snapshot, user["tg_id"])
    pct = share_percentage(amount, company["total_shares"])
    value = amount * company["share_price"]
    text = (
        "📈 <b>Мои акции</b>\n\n"
        f"Пакет: {format_shares(amount)} акций ({format_percent(pct)})\n"
        f"Цена акции: {format_money(company['share_price'])}\n"
        f"Стоимость пакета: {format_money(value)}"
    )
    await query.edit_message_text(text, reply_markup=kb.shares_menu(), parse_mode="HTML")


async def start_share_transfer(query, context, user: dict) -> None:
    snapshot = db.load()
    others = db.other_users(snapshot, user["tg_id"])
    if not others:
        await query.edit_message_text("Пока нет других зарегистрированных пользователей.", reply_markup=kb.back_to_menu())
        return
    if db.get_shares(snapshot, user["tg_id"]) <= 0:
        await query.answer("У вас нет акций для передачи", show_alert=True)
        return
    context.user_data["flow"] = "share_transfer"
    await query.edit_message_text("🔁 Кому передать акции?", reply_markup=kb.user_picker(others, "co:shtr"))


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def _format_task_card(task: dict, total_shares: int) -> str:
    yes_w = len(task["votes_yes"])
    no_w = len(task["votes_no"])
    status_labels = {
        "open": "🟡 Открыто",
        "completed": "✅ Выполнено",
        "rejected": "❌ Отклонено",
        "overdue": "⌛ Просрочено",
    }
    lines = [
        f"<b>{task['title']}</b>",
        task.get("description") or "(без описания)",
        "",
        f"Награда: {format_money(task['reward_base'])}",
        f"Статус: {status_labels.get(task['status'], task['status'])}",
        f"Дедлайн: {task['deadline'][:16].replace('T', ' ')}",
        f"Голосов за: {yes_w} · против: {no_w}",
    ]
    return "\n".join(lines)


async def show_tasks_menu(query) -> None:
    await query.edit_message_text("📝 <b>Задания</b>\n\nВыберите действие:", reply_markup=kb.tasks_menu(), parse_mode="HTML")


async def start_task_creation(query, context) -> None:
    context.user_data["flow"] = "task_new"
    context.user_data["new_task"] = {}
    context.user_data["awaiting"] = "task_title"
    await query.edit_message_text("➕ Введите заголовок задания:")


async def show_task_list(query, status: str, page: int) -> None:
    snapshot = db.load()
    tasks = [t for t in snapshot["tasks"] if (t["status"] == "open" if status == "open" else t["status"] != "open")]
    tasks.sort(key=lambda t: t["created_at"], reverse=True)
    start, end = page * TASK_PAGE_SIZE, (page + 1) * TASK_PAGE_SIZE
    chunk = tasks[start:end]
    if not chunk and page > 0:
        page = 0
        chunk = tasks[0:TASK_PAGE_SIZE]
    title = "📋 Открытые задания" if status == "open" else "✅ Закрытые задания"
    if not chunk:
        await query.edit_message_text(f"{title}\n\nПусто.", reply_markup=kb.task_list_nav(status, page, False))
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(t["title"], callback_data=f"co:task:view:{t['id']}")] for t in chunk]
    nav = kb.task_list_nav(status, page, end < len(tasks))
    rows = rows + [list(row) for row in nav.inline_keyboard]
    await query.edit_message_text(f"{title}:", reply_markup=InlineKeyboardMarkup(rows))


async def show_task_view(query, task_id: str) -> None:
    snapshot = db.load()
    task = next((t for t in snapshot["tasks"] if t["id"] == task_id), None)
    if task is None:
        await query.answer("Задание не найдено", show_alert=True)
        return
    tg_id = query.from_user.id
    voted = tg_id in task["votes_yes"] or tg_id in task["votes_no"]
    can_vote = task["status"] == "open" and db.get_shares(snapshot, tg_id) > 0 and not voted
    text = _format_task_card(task, snapshot["company"]["total_shares"])
    markup = kb.task_card(task_id, voted=not can_vote)
    await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")


async def cast_task_vote(query, context, task_id: str, choice: str) -> None:
    tg_id = query.from_user.id
    outcome = None
    task_snapshot = None
    with db.transaction() as data:
        task = next((t for t in data["tasks"] if t["id"] == task_id), None)
        if task is None or task["status"] != "open":
            await query.answer("Голосование по этому заданию уже закрыто", show_alert=True)
            return
        weight = db.get_shares(data, tg_id)
        if weight <= 0:
            await query.answer("У вас нет акций, голос не учитывается", show_alert=True)
            return
        if tg_id in task["votes_yes"] or tg_id in task["votes_no"]:
            await query.answer("Вы уже проголосовали", show_alert=True)
            return
        if choice == "yes":
            task["votes_yes"].append(tg_id)
        else:
            task["votes_no"].append(tg_id)

        total_shares = data["company"]["total_shares"]
        threshold = data["settings"]["task_vote_threshold"]
        yes_weight = vote_weights(data["shares"], set(task["votes_yes"]))
        no_weight = vote_weights(data["shares"], set(task["votes_no"]))

        if threshold_reached(yes_weight, total_shares, threshold):
            outcome = "completed"
        elif threshold_reached(no_weight, total_shares, threshold):
            outcome = "rejected"

        if outcome is not None:
            task["status"] = outcome
            task["closed_at"] = db.now_iso()
            if outcome == "completed":
                settings = data["settings"]
                multiplier = settings["task_reward_multiplier"]
                if data["company"]["penalty_active"]:
                    multiplier *= settings["penalty_multiplier"]
                reward = round(task["reward_base"] * multiplier, 2)
                data["company"]["cash_reserve"] = round(data["company"]["cash_reserve"] + reward, 2)
                data["company"]["daily_profit"] = round(data["company"].get("daily_profit", 0.0) + reward, 2)
                db.add_transaction(data, "profit", reward, to_id=None, description=f"Задание «{task['title']}»")
                data["company"]["consecutive_success_count"] = data["company"].get("consecutive_success_count", 0) + 1
                if data["company"]["penalty_active"] and data["company"]["consecutive_success_count"] >= settings["penalty_reset_tasks"]:
                    data["company"]["penalty_active"] = False
                    data["company"]["consecutive_success_count"] = 0
        task_snapshot = dict(task)

    await query.answer("Голос учтён")
    await show_task_view(query, task_id)

    author_id = task_snapshot["author_id"]
    assignee_id = task_snapshot["assignee_id"]
    recipients = {author_id, assignee_id} - {tg_id}
    vote_word = "за выполнение" if choice == "yes" else "против выполнения"
    for rid in recipients:
        await notify(context.bot, rid, f"🗳 По заданию «{task_snapshot['title']}» подан голос {vote_word}.")

    if outcome == "completed":
        for rid in {author_id, assignee_id}:
            await notify(context.bot, rid, f"✅ Задание «{task_snapshot['title']}» выполнено! Прибыль зачислена в кассу компании.")
    elif outcome == "rejected":
        for rid in {author_id, assignee_id}:
            await notify(context.bot, rid, f"❌ Задание «{task_snapshot['title']}» отклонено голосованием.")


# ---------------------------------------------------------------------------
# Votes (shareholder council)
# ---------------------------------------------------------------------------

def _format_vote_card(vote: dict, total_shares: int) -> str:
    type_labels = {"issue_shares": "Эмиссия акций", "settings": "Изменение настроек", "custom": "Своё голосование"}
    yes_w = len(vote["votes_yes"])
    no_w = len(vote["votes_no"])
    lines = [
        f"<b>{vote['title']}</b>",
        f"Тип: {type_labels.get(vote['type'], vote['type'])}",
        f"Статус: {vote['status']}",
        f"Голосов за: {yes_w} · против: {no_w}",
        f"Закрывается: {vote['closes_at'][:16].replace('T', ' ')}",
    ]
    return "\n".join(lines)


async def show_votes_menu(query) -> None:
    await query.edit_message_text("🗳 <b>Голосования</b>\n\nВыберите действие:", reply_markup=kb.votes_menu(), parse_mode="HTML")


async def start_vote_creation(query, context, vote_type: str) -> None:
    user = await _require_user(query)
    if user is None:
        return
    if db.get_shares(db.load(), user["tg_id"]) <= 0:
        await query.answer("Для создания голосования нужны акции", show_alert=True)
        return
    context.user_data["new_vote"] = {"type": vote_type}
    if vote_type == "issue_shares":
        context.user_data["awaiting"] = "vote_issue_amount"
        await query.edit_message_text("🗳 <b>Эмиссия акций</b>\n\nСколько акций выпустить?", parse_mode="HTML")
    elif vote_type == "settings":
        await query.edit_message_text("⚙️ Какую настройку изменить?", reply_markup=kb.setting_picker())
    else:
        context.user_data["awaiting"] = "vote_custom_title"
        await query.edit_message_text("💬 Введите тему голосования:")


async def _create_vote(context, creator_id: int, vote_type: str, title: str, payload: dict) -> dict:
    with db.transaction() as data:
        vote = {
            "id": db.new_id("v"),
            "type": vote_type,
            "title": title,
            "payload": payload,
            "votes_yes": [],
            "votes_no": [],
            "status": "open",
            "created_at": db.now_iso(),
            "closes_at": (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        data["votes"].append(vote)
        holders = db.shareholders(data)
    for holder_user, _ in holders:
        if holder_user["tg_id"] != creator_id:
            await notify(context.bot, holder_user["tg_id"], f"🗳 Новое голосование: «{title}». Загляните в раздел «Голосования».")
    return vote


async def show_vote_list(query, page: int) -> None:
    snapshot = db.load()
    votes = [v for v in snapshot["votes"] if v["status"] == "open"]
    votes.sort(key=lambda v: v["created_at"], reverse=True)
    start, end = page * VOTE_PAGE_SIZE, (page + 1) * VOTE_PAGE_SIZE
    chunk = votes[start:end]
    if not chunk and page > 0:
        page = 0
        chunk = votes[0:VOTE_PAGE_SIZE]
    if not chunk:
        await query.edit_message_text("📋 Активные голосования\n\nПусто.", reply_markup=kb.vote_list_nav(page, False))
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(v["title"], callback_data=f"co:vote:view:{v['id']}")] for v in chunk]
    nav = kb.vote_list_nav(page, end < len(votes))
    rows = rows + [list(row) for row in nav.inline_keyboard]
    await query.edit_message_text("📋 Активные голосования:", reply_markup=InlineKeyboardMarkup(rows))


async def show_vote_view(query, vote_id: str) -> None:
    snapshot = db.load()
    vote = next((v for v in snapshot["votes"] if v["id"] == vote_id), None)
    if vote is None:
        await query.answer("Голосование не найдено", show_alert=True)
        return
    tg_id = query.from_user.id
    voted = tg_id in vote["votes_yes"] or tg_id in vote["votes_no"]
    can_vote = vote["status"] == "open" and db.get_shares(snapshot, tg_id) > 0 and not voted
    text = _format_vote_card(vote, snapshot["company"]["total_shares"])
    await query.edit_message_text(text, reply_markup=kb.vote_card(vote_id, voted=not can_vote), parse_mode="HTML")


def _apply_vote_outcome(data: dict, vote: dict, passed: bool) -> None:
    vote["status"] = "passed" if passed else "rejected"
    if not passed:
        return
    if vote["type"] == "issue_shares":
        amount = int(vote["payload"]["amount"])
        distribution = vote["payload"]["distribution"]
        holders = [(s["tg_id"], s["amount"]) for s in data["shares"] if s["amount"] > 0]
        data["company"]["total_shares"] += amount
        if not holders:
            return
        if distribution == "equal":
            share_each = amount // len(holders)
            remainder = amount - share_each * len(holders)
            for i, (tg_id, _) in enumerate(holders):
                extra = remainder if i == 0 else 0
                db.add_shares(data, tg_id, share_each + extra)
        else:
            total_existing = sum(a for _, a in holders)
            distributed = 0
            for i, (tg_id, amt) in enumerate(holders):
                if i == len(holders) - 1:
                    piece = amount - distributed
                else:
                    piece = int(amount * amt / total_existing)
                    distributed += piece
                db.add_shares(data, tg_id, piece)
    elif vote["type"] == "settings":
        key = vote["payload"]["setting_key"]
        value = vote["payload"]["new_value"]
        data["settings"][key] = value


async def cast_vote(query, context, vote_id: str, choice: str) -> None:
    tg_id = query.from_user.id
    outcome = None
    vote_snapshot = None
    with db.transaction() as data:
        vote = next((v for v in data["votes"] if v["id"] == vote_id), None)
        if vote is None or vote["status"] != "open":
            await query.answer("Голосование уже закрыто", show_alert=True)
            return
        weight = db.get_shares(data, tg_id)
        if weight <= 0:
            await query.answer("У вас нет акций, голос не учитывается", show_alert=True)
            return
        if tg_id in vote["votes_yes"] or tg_id in vote["votes_no"]:
            await query.answer("Вы уже проголосовали", show_alert=True)
            return
        if choice == "yes":
            vote["votes_yes"].append(tg_id)
        else:
            vote["votes_no"].append(tg_id)

        total_shares = data["company"]["total_shares"]
        threshold = data["settings"]["issue_vote_threshold"] if vote["type"] in ("issue_shares", "settings") else data["settings"]["task_vote_threshold"]
        yes_weight = vote_weights(data["shares"], set(vote["votes_yes"]))
        no_weight = vote_weights(data["shares"], set(vote["votes_no"]))

        if threshold_reached(yes_weight, total_shares, threshold):
            _apply_vote_outcome(data, vote, passed=True)
            outcome = "passed"
        elif threshold_reached(no_weight, total_shares, threshold):
            _apply_vote_outcome(data, vote, passed=False)
            outcome = "rejected"
        vote_snapshot = dict(vote)

    await query.answer("Голос учтён")
    await show_vote_view(query, vote_id)

    if outcome is not None:
        snapshot = db.load()
        holders = db.shareholders(snapshot)
        result_word = "принято" if outcome == "passed" else "отклонено"
        for holder_user, _ in holders:
            await notify(context.bot, holder_user["tg_id"], f"🗳 Голосование «{vote_snapshot['title']}» завершено: {result_word}.")


# ---------------------------------------------------------------------------
# Shareholders / profile
# ---------------------------------------------------------------------------

async def show_shareholders(query) -> None:
    snapshot = db.load()
    company = db.get_company(snapshot)
    holders = db.shareholders(snapshot)
    if not holders:
        text = "👥 <b>Акционеры</b>\n\nПока нет держателей акций."
    else:
        lines = []
        for holder_user, amount in holders:
            pct = share_percentage(amount, company["total_shares"])
            lines.append(f"{holder_user['name']} ({holder_user['role']}) — {format_shares(amount)} акций ({format_percent(pct)})")
        text = "👥 <b>Акционеры</b>\n\n" + "\n".join(lines)
    await query.edit_message_text(text, reply_markup=kb.shareholders_menu(), parse_mode="HTML")


async def show_profile(query, user: dict) -> None:
    snapshot = db.load()
    company = db.get_company(snapshot)
    amount = db.get_shares(snapshot, user["tg_id"])
    value = amount * company["share_price"]
    text = (
        "💼 <b>Профиль</b>\n\n"
        f"Имя: {user['name']}\n"
        f"Роль: {user['role']}\n"
        f"ID: <code>{user['tg_id']}</code>\n\n"
        f"Наличные: {format_money(user['cash'])}\n"
        f"Вклад: {format_money(user['deposit'])}\n"
        f"Акции: {format_shares(amount)} ({format_money(value)})"
    )
    await query.edit_message_text(text, reply_markup=kb.profile_menu(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Main callback dispatcher
# ---------------------------------------------------------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data_str = query.data
    parts = data_str.split(":")
    action = parts[1] if len(parts) > 1 else ""

    user = await _require_user(query)
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
            "📊 Дашборд — состояние компании и цена акции\n"
            "📈 Акции — ваш пакет, передача акций, эмиссия\n"
            "📝 Задания — создавайте задания и голосуйте за их выполнение\n"
            "🗳 Голосования — совет акционеров: эмиссия, настройки, другое\n"
            "👥 Акционеры — список держателей акций\n"
            "💼 Профиль — ваши данные и переход в банк",
            reply_markup=kb.back_to_menu(),
            parse_mode="HTML",
        )
        return

    if action == "dash" and len(parts) == 2:
        await show_dashboard(query, user)
        return
    if action == "dash" and parts[2] == "chart":
        await show_price_chart(query, context)
        return
    if action == "dash" and parts[2] == "tx":
        await show_dashboard_tx(query)
        return

    if action == "shares" and len(parts) == 2:
        await show_shares(query, user)
        return
    if action == "shares" and parts[2] == "transfer":
        await start_share_transfer(query, context, user)
        return

    if action == "shtr" and parts[2] == "user":
        recipient_id = int(parts[3])
        context.user_data["share_transfer_to"] = recipient_id
        await query.edit_message_text(
            "Сколько акций передать?",
            reply_markup=kb.amount_picker("co:shtr", [10, 50, 100]),
        )
        return
    if action == "shtr" and parts[2] == "amt":
        recipient_id = context.user_data.get("share_transfer_to")
        if recipient_id is None:
            await show_main_menu(query)
            return
        if parts[3] == "custom":
            context.user_data["awaiting"] = "shares_transfer_custom"
            await query.edit_message_text("✏️ Введите количество акций числом:")
            return
        amount = int(parts[3])
        snapshot = db.load()
        if amount > db.get_shares(snapshot, tg_id):
            await query.answer("У вас недостаточно акций", show_alert=True)
            return
        recipient = db.get_user(snapshot, recipient_id)
        await query.edit_message_text(
            f"Передать {format_shares(amount)} акций пользователю {recipient['name']}?",
            reply_markup=kb.confirm_cancel(f"co:shtr:confirm:{amount}"),
        )
        return
    if action == "shtr" and parts[2] == "confirm":
        amount = int(parts[3])
        recipient_id = context.user_data.get("share_transfer_to")
        with db.transaction() as data:
            sender_shares = db.get_shares(data, tg_id)
            if recipient_id is None or amount > sender_shares:
                await query.answer("Недостаточно акций или ошибка данных", show_alert=True)
                return
            db.add_shares(data, tg_id, -amount)
            db.add_shares(data, recipient_id, amount)
            recipient = db.get_user(data, recipient_id)
            db.add_transaction(data, "share_transfer", amount, from_id=tg_id, to_id=recipient_id, description=recipient["name"])
            recipient_name = recipient["name"]
        context.user_data.clear()
        await query.edit_message_text(f"✅ Передано {format_shares(amount)} акций пользователю {recipient_name}.", reply_markup=kb.back_to_menu())
        await notify(context.bot, recipient_id, f"📈 Вам передали {format_shares(amount)} акций от {user['name']}.")
        return

    if action == "tasks":
        await show_tasks_menu(query)
        return
    if action == "task" and parts[2] == "new":
        await start_task_creation(query, context)
        return
    if action == "task" and parts[2] == "skip_desc":
        context.user_data["new_task"]["description"] = ""
        context.user_data.pop("awaiting", None)
        await query.edit_message_text("Выберите базовую награду:", reply_markup=kb.reward_picker())
        return
    if action == "task" and parts[2] == "reward" and parts[3] == "amt":
        if parts[4] == "custom":
            context.user_data["awaiting"] = "task_reward_custom"
            await query.edit_message_text("✏️ Введите сумму награды числом:")
            return
        context.user_data["new_task"]["reward_base"] = float(parts[4])
        snapshot = db.load()
        others = db.other_users(snapshot, tg_id)
        if not others:
            others = [user]
        await query.edit_message_text("Кто исполнитель?", reply_markup=kb.user_picker(others, "co:task:assignee"))
        return
    if action == "task" and parts[2] == "assignee" and parts[3] == "user":
        context.user_data["new_task"]["assignee_id"] = int(parts[4])
        await query.edit_message_text("Выберите дедлайн:", reply_markup=kb.deadline_picker())
        return
    if action == "task" and parts[2] == "deadline":
        code = parts[3]
        delta = DEADLINE_CODES.get(code, timedelta(days=1))
        deadline = (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
        context.user_data["new_task"]["deadline"] = deadline
        nt = context.user_data["new_task"]
        summary = (
            f"Заголовок: {nt['title']}\n"
            f"Описание: {nt.get('description') or '(без описания)'}\n"
            f"Награда: {format_money(nt['reward_base'])}\n"
            f"Дедлайн: {deadline[:16].replace('T', ' ')}\n\nСоздать задание?"
        )
        await query.edit_message_text(summary, reply_markup=kb.confirm_cancel("co:task:confirm"))
        return
    if action == "task" and parts[2] == "confirm":
        nt = context.user_data.get("new_task")
        if not nt or "assignee_id" not in nt:
            await query.answer("Данные задания утеряны, начните заново", show_alert=True)
            await show_main_menu(query)
            return
        task_id = db.new_id("t")
        with db.transaction() as data:
            task = {
                "id": task_id,
                "title": nt["title"],
                "description": nt.get("description", ""),
                "reward_base": nt["reward_base"],
                "author_id": tg_id,
                "assignee_id": nt["assignee_id"],
                "status": "open",
                "votes_yes": [],
                "votes_no": [],
                "created_at": db.now_iso(),
                "deadline": nt["deadline"],
                "closed_at": None,
            }
            data["tasks"].append(task)
            assignee_id = nt["assignee_id"]
        context.user_data.clear()
        await query.edit_message_text("✅ Задание создано!", reply_markup=kb.back_to_menu())
        if assignee_id != tg_id:
            await notify(context.bot, assignee_id, f"📝 Вам назначено новое задание: «{task['title']}».")
        return
    if action == "task" and parts[2] == "list":
        status, page = parts[3], int(parts[4])
        await show_task_list(query, status, page)
        return
    if action == "task" and parts[2] == "view":
        await show_task_view(query, parts[3])
        return
    if action == "task" and parts[2] == "vote":
        await cast_task_vote(query, context, parts[3], parts[4])
        return

    if action == "votes":
        await show_votes_menu(query)
        return
    if action == "vote" and parts[2] == "new":
        await start_vote_creation(query, context, parts[3])
        return
    if action == "vote" and parts[2] == "custom" and parts[3] == "skip":
        nv = context.user_data.get("new_vote")
        if not nv or "title" not in nv:
            await query.answer("Данные голосования утеряны, начните заново", show_alert=True)
            await show_main_menu(query)
            return
        await _create_vote(context, tg_id, "custom", nv["title"], {"description": ""})
        context.user_data.clear()
        await query.edit_message_text("💬 Голосование создано.", reply_markup=kb.back_to_menu())
        return
    if action == "vote" and parts[2] == "dist":
        distribution = parts[3]
        nv = context.user_data.get("new_vote", {})
        payload = {"amount": nv.get("amount"), "distribution": distribution}
        vote = await _create_vote(context, tg_id, "issue_shares", f"Выпустить {int(nv.get('amount', 0))} акций", payload)
        context.user_data.clear()
        await query.edit_message_text("🗳 Голосование по эмиссии создано.", reply_markup=kb.back_to_menu())
        return
    if action == "vote" and parts[2] == "setting":
        key = parts[3]
        context.user_data.setdefault("new_vote", {"type": "settings"})["setting_key"] = key
        context.user_data["awaiting"] = "vote_setting_value"
        await query.edit_message_text(f"Введите новое значение для «{key}»:")
        return
    if action == "vote" and parts[2] == "list":
        page = int(parts[3])
        await show_vote_list(query, page)
        return
    if action == "vote" and parts[2] == "view":
        await show_vote_view(query, parts[3])
        return
    if action == "vote" and parts[2] == "cast":
        await cast_vote(query, context, parts[3], parts[4])
        return

    if action == "shareholders":
        await show_shareholders(query)
        return
    if action == "profile":
        await show_profile(query, user)
        return


# ---------------------------------------------------------------------------
# Text input dispatcher
# ---------------------------------------------------------------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await on_text_registration(update, context):
        return

    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return
    tg_id = update.effective_user.id
    snapshot = db.load()
    user = db.get_user(snapshot, tg_id)
    if user is None:
        return

    if awaiting == "task_title":
        title = update.message.text.strip()
        if not title:
            await update.message.reply_text("Заголовок не может быть пустым. Попробуйте ещё раз:")
            return
        context.user_data["new_task"]["title"] = title
        context.user_data["awaiting"] = "task_description"
        await update.message.reply_text(
            "Введите описание задания (или нажмите «Пропустить»):",
            reply_markup=kb.skip_or_cancel("co:task:skip_desc"),
        )
        return

    if awaiting == "task_description":
        text = update.message.text.strip()
        if text.lower() in ("пропустить", "skip", "-"):
            text = ""
        context.user_data["new_task"]["description"] = text
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("Выберите базовую награду:", reply_markup=kb.reward_picker())
        return

    if awaiting == "task_reward_custom":
        value = _parse_number(update.message.text)
        if value is None or value <= 0:
            await update.message.reply_text("Введите положительное число, например 150.")
            return
        context.user_data["new_task"]["reward_base"] = value
        context.user_data.pop("awaiting", None)
        others = db.other_users(snapshot, tg_id) or [user]
        await update.message.reply_text("Кто исполнитель?", reply_markup=kb.user_picker(others, "co:task:assignee"))
        return

    if awaiting == "shares_transfer_custom":
        recipient_id = context.user_data.get("share_transfer_to")
        value = _parse_number(update.message.text)
        if value is None or value <= 0 or value != int(value):
            await update.message.reply_text("Введите целое положительное число акций.")
            return
        amount = int(value)
        if recipient_id is None:
            context.user_data.clear()
            await update.message.reply_text("Начните заново: /start")
            return
        if amount > db.get_shares(snapshot, tg_id):
            await update.message.reply_text("У вас недостаточно акций.")
            return
        recipient = db.get_user(snapshot, recipient_id)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(
            f"Передать {format_shares(amount)} акций пользователю {recipient['name']}?",
            reply_markup=kb.confirm_cancel(f"co:shtr:confirm:{amount}"),
        )
        return

    if awaiting == "vote_issue_amount":
        value = _parse_number(update.message.text)
        if value is None or value <= 0 or value != int(value):
            await update.message.reply_text("Введите целое положительное число акций.")
            return
        context.user_data["new_vote"]["amount"] = int(value)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("Как распределить новые акции?", reply_markup=kb.distribution_picker())
        return

    if awaiting == "vote_setting_value":
        value = _parse_number(update.message.text)
        if value is None:
            await update.message.reply_text("Введите число, например 0.3 для 30%.")
            return
        nv = context.user_data["new_vote"]
        key = nv["setting_key"]
        await _create_vote(
            context, tg_id, "settings", f"Изменить {key} на {value}",
            {"setting_key": key, "new_value": value},
        )
        context.user_data.clear()
        await update.message.reply_text("⚙️ Голосование по изменению настройки создано.", reply_markup=kb.back_to_menu())
        return

    if awaiting == "vote_custom_title":
        title = update.message.text.strip()
        if not title:
            await update.message.reply_text("Тема не может быть пустой. Введите ещё раз:")
            return
        context.user_data["new_vote"]["title"] = title
        context.user_data["awaiting"] = "vote_custom_description"
        await update.message.reply_text("Введите описание (или «Пропустить»):", reply_markup=kb.skip_or_cancel("co:vote:custom:skip"))
        return

    if awaiting == "vote_custom_description":
        text = update.message.text.strip()
        if text.lower() in ("пропустить", "skip", "-"):
            text = ""
        nv = context.user_data["new_vote"]
        await _create_vote(context, tg_id, "custom", nv["title"], {"description": text})
        context.user_data.clear()
        await update.message.reply_text("💬 Голосование создано.", reply_markup=kb.back_to_menu())
        return
