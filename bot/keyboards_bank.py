from telegram import InlineKeyboardButton, InlineKeyboardMarkup

QUICK_AMOUNTS = [1000, 5000, 10000]


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Мой счёт", callback_data="bank:account"),
             InlineKeyboardButton("💎 Вклад", callback_data="bank:deposit")],
            [InlineKeyboardButton("💸 Перевод", callback_data="bank:transfer"),
             InlineKeyboardButton("📜 История", callback_data="bank:history:0")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="bank:help")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="co:menu")],
        ]
    )


def account_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💎 Открыть вклад", callback_data="bank:deposit:open")],
            [InlineKeyboardButton("💸 Перевести", callback_data="bank:transfer")],
            [InlineKeyboardButton("🔙 Назад", callback_data="bank:menu")],
        ]
    )


def deposit_menu(has_deposit: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_deposit:
        rows.append([InlineKeyboardButton("🔓 Закрыть вклад", callback_data="bank:deposit:close")])
        rows.append([InlineKeyboardButton("📊 Статистика", callback_data="bank:deposit:stats")])
    else:
        rows.append([InlineKeyboardButton("💎 Открыть", callback_data="bank:deposit:open")])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="bank:menu")])
    return InlineKeyboardMarkup(rows)


def amount_picker(prefix: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(f"{a:,}".replace(",", " ") + " ₽", callback_data=f"{prefix}:amt:{a}") for a in QUICK_AMOUNTS]
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("✏️ Своя сумма", callback_data=f"{prefix}:amt:custom")],
            [InlineKeyboardButton("❌ Отмена", callback_data="bank:cancel")],
        ]
    )


def confirm_cancel(confirm_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подтвердить", callback_data=confirm_cb),
             InlineKeyboardButton("❌ Отмена", callback_data="bank:cancel")],
        ]
    )


def user_picker(users: list, prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        rows.append([InlineKeyboardButton(f"{u['name']} ({u['role']})", callback_data=f"{prefix}:user:{u['tg_id']}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="bank:cancel")])
    return InlineKeyboardMarkup(rows)


def history_nav(page: int, has_more: bool) -> InlineKeyboardMarkup:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"bank:history:{page - 1}"))
    if has_more:
        row.append(InlineKeyboardButton("▶️", callback_data=f"bank:history:{page + 1}"))
    rows = [row] if row else []
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="bank:menu")])
    return InlineKeyboardMarkup(rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="bank:menu")]])
