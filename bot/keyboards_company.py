from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from common.db import ROLES

REWARD_PRESETS = [50, 100, 200, 500]
DEADLINE_PRESETS = [
    ("Сегодня", "today"),
    ("Завтра", "tomorrow"),
    ("3 дня", "3d"),
    ("Неделя", "week"),
]


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Дашборд", callback_data="co:dash"),
             InlineKeyboardButton("📈 Акции", callback_data="co:shares")],
            [InlineKeyboardButton("📝 Задания", callback_data="co:tasks"),
             InlineKeyboardButton("🗳 Голосования", callback_data="co:votes")],
            [InlineKeyboardButton("👥 Акционеры", callback_data="co:shareholders"),
             InlineKeyboardButton("💼 Профиль", callback_data="co:profile")],
            [InlineKeyboardButton("💰 Банк", callback_data="bank:menu"),
             InlineKeyboardButton("ℹ️ Помощь", callback_data="co:help")],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="co:menu")]])


def role_picker() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(r, callback_data=f"reg:role:{r}")] for r in ROLES]
    return InlineKeyboardMarkup(rows)


def dashboard_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📈 График цены", callback_data="co:dash:chart")],
            [InlineKeyboardButton("📜 Транзакции", callback_data="co:dash:tx")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:menu")],
        ]
    )


def shares_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 Передать акции", callback_data="co:shares:transfer")],
            [InlineKeyboardButton("🗳 Голосовать за эмиссию", callback_data="co:vote:new:issue_shares")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:menu")],
        ]
    )


def user_picker(users: list, prefix: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{u['name']} ({u['role']})", callback_data=f"{prefix}:user:{u['tg_id']}")] for u in users]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")])
    return InlineKeyboardMarkup(rows)


def amount_picker(prefix: str, presets: list) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(str(a), callback_data=f"{prefix}:amt:{a}") for a in presets]
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("✏️ Своё значение", callback_data=f"{prefix}:amt:custom")],
            [InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")],
        ]
    )


def confirm_cancel(confirm_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Подтвердить", callback_data=confirm_cb),
          InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")]]
    )


def tasks_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Создать задание", callback_data="co:task:new")],
            [InlineKeyboardButton("📋 Открытые", callback_data="co:task:list:open:0")],
            [InlineKeyboardButton("✅ Закрытые", callback_data="co:task:list:closed:0")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:menu")],
        ]
    )


def skip_or_cancel(skip_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("➡️ Пропустить", callback_data=skip_cb),
          InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")]]
    )


def reward_picker() -> InlineKeyboardMarkup:
    return amount_picker("co:task:reward", REWARD_PRESETS)


def deadline_picker() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, callback_data=f"co:task:deadline:{code}")] for label, code in DEADLINE_PRESETS]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")])
    return InlineKeyboardMarkup(rows)


def task_list_nav(status: str, page: int, has_more: bool) -> InlineKeyboardMarkup:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"co:task:list:{status}:{page - 1}"))
    if has_more:
        row.append(InlineKeyboardButton("▶️", callback_data=f"co:task:list:{status}:{page + 1}"))
    rows = [row] if row else []
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="co:tasks")])
    return InlineKeyboardMarkup(rows)


def task_card(task_id: str, voted: bool) -> InlineKeyboardMarkup:
    if voted:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="co:task:list:open:0")]])
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"co:task:vote:{task_id}:yes"),
             InlineKeyboardButton("❌ Не выполнено", callback_data=f"co:task:vote:{task_id}:no")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:task:list:open:0")],
        ]
    )


def votes_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗳 Эмиссия акций", callback_data="co:vote:new:issue_shares")],
            [InlineKeyboardButton("⚙️ Изменить настройки", callback_data="co:vote:new:settings")],
            [InlineKeyboardButton("💬 Своё голосование", callback_data="co:vote:new:custom")],
            [InlineKeyboardButton("📋 Активные голосования", callback_data="co:vote:list:0")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:menu")],
        ]
    )


def distribution_picker() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Поровну", callback_data="co:vote:dist:equal")],
            [InlineKeyboardButton("Пропорционально", callback_data="co:vote:dist:proportional")],
            [InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")],
        ]
    )


def setting_picker() -> InlineKeyboardMarkup:
    settings = [
        ("Ставка дивидендов", "dividend_rate"),
        ("Множитель награды за задания", "task_reward_multiplier"),
        ("Множитель штрафа", "penalty_multiplier"),
        ("k_profit", "k_profit"),
        ("k_penalty", "k_penalty"),
    ]
    rows = [[InlineKeyboardButton(label, callback_data=f"co:vote:setting:{key}")] for label, key in settings]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="co:cancel")])
    return InlineKeyboardMarkup(rows)


def vote_list_nav(page: int, has_more: bool) -> InlineKeyboardMarkup:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"co:vote:list:{page - 1}"))
    if has_more:
        row.append(InlineKeyboardButton("▶️", callback_data=f"co:vote:list:{page + 1}"))
    rows = [row] if row else []
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="co:votes")])
    return InlineKeyboardMarkup(rows)


def vote_card(vote_id: str, voted: bool) -> InlineKeyboardMarkup:
    if voted:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="co:vote:list:0")]])
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ За", callback_data=f"co:vote:cast:{vote_id}:yes"),
             InlineKeyboardButton("❌ Против", callback_data=f"co:vote:cast:{vote_id}:no")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:vote:list:0")],
        ]
    )


def shareholders_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 Передать акции", callback_data="co:shares:transfer")],
            [InlineKeyboardButton("🗳 Создать голосование", callback_data="co:votes")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:menu")],
        ]
    )


def profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Перейти в банк", callback_data="bank:menu")],
            [InlineKeyboardButton("🔙 Назад", callback_data="co:menu")],
        ]
    )
