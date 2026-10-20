import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from common import db
from common.models import daily_deposit_interest, recalc_share_price
from common.money import format_money
from common.notify import notify

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bank: daily deposit interest capitalization
# ---------------------------------------------------------------------------

async def capitalize_deposits(bot) -> None:
    today = db.today_str()
    to_notify = []
    with db.transaction() as data:
        rate = data["settings"]["deposit_rate_annual"]
        for user in data["users"]:
            if user["deposit"] <= 0:
                continue
            if user.get("deposit_last_capitalized_at") == today:
                continue
            interest = round(daily_deposit_interest(user["deposit"], rate), 2)
            if interest <= 0:
                continue
            user["deposit"] = round(user["deposit"] + interest, 2)
            user["deposit_interest_accrued"] = round(user.get("deposit_interest_accrued", 0.0) + interest, 2)
            user["deposit_last_capitalized_at"] = today
            db.add_transaction(
                data, "deposit_interest", interest, to_id=user["tg_id"],
                description="Капитализация процентов по вкладу",
            )
            to_notify.append((user["tg_id"], interest, user["deposit"]))

    for tg_id, interest, new_deposit in to_notify:
        await notify(
            bot, tg_id,
            f"💎 Начислено {format_money(interest)} процентов по вкладу.\n"
            f"Новый размер вклада: {format_money(new_deposit)}.",
        )


# ---------------------------------------------------------------------------
# Company: overdue tasks, share price, dividends
# ---------------------------------------------------------------------------

async def check_overdue_tasks(bot) -> None:
    now = datetime.now(timezone.utc)
    overdue = []
    with db.transaction() as data:
        for task in data["tasks"]:
            if task["status"] != "open":
                continue
            deadline = datetime.strptime(task["deadline"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if deadline >= now:
                continue
            task["status"] = "overdue"
            task["closed_at"] = db.now_iso()
            data["company"]["daily_overdue_count"] = data["company"].get("daily_overdue_count", 0) + 1
            data["company"]["penalty_active"] = True
            data["company"]["consecutive_success_count"] = 0
            db.add_transaction(data, "task_penalty", 0, description=f"Просрочено: «{task['title']}»")
            overdue.append(dict(task))

    for task in overdue:
        for rid in {task["author_id"], task["assignee_id"]}:
            await notify(bot, rid, f"⌛ Задание «{task['title']}» просрочено. Цена акции может упасть.")


async def recalc_price(bot) -> None:
    today = db.today_str()
    with db.transaction() as data:
        company = data["company"]
        if company.get("last_price_update_at", "")[:10] == today:
            return
        settings = data["settings"]
        open_task_count = len([t for t in data["tasks"] if t["status"] == "open"]) + company.get("daily_overdue_count", 0)
        new_price = recalc_share_price(
            base_price=settings.get("base_price", 100.0),
            daily_profit=company.get("daily_profit", 0.0),
            profit_baseline=settings.get("price_profit_baseline", 1000.0),
            overdue_count=company.get("daily_overdue_count", 0),
            open_task_count=open_task_count,
            k_profit=settings["k_profit"],
            k_penalty=settings["k_penalty"],
        )
        company["share_price"] = new_price
        company["last_price_update_at"] = db.now_iso()
        company["price_history"].append({"date": today, "price": new_price})
        company["daily_profit"] = 0.0
        company["daily_overdue_count"] = 0


async def pay_dividends(bot) -> None:
    today = db.today_str()
    notifications = []
    with db.transaction() as data:
        company = data["company"]
        if company.get("last_dividend_at", "")[:10] == today:
            return
        company["last_dividend_at"] = db.now_iso()
        payout_pool = round(company["cash_reserve"] * data["settings"]["dividend_rate"], 2)
        holders = db.shareholders(data)
        if payout_pool <= 0 or not holders:
            for holder_user, _ in holders:
                notifications.append((holder_user["tg_id"], None))
        else:
            total_shares_held = sum(amount for _, amount in holders)
            distributed = 0.0
            for i, (holder_user, amount) in enumerate(holders):
                if i == len(holders) - 1:
                    share_amount = round(payout_pool - distributed, 2)
                else:
                    share_amount = round(payout_pool * amount / total_shares_held, 2)
                    distributed += share_amount
                if share_amount <= 0:
                    continue
                holder_user["cash"] = round(holder_user["cash"] + share_amount, 2)
                db.add_transaction(data, "dividend", share_amount, to_id=holder_user["tg_id"], description="Дивиденды")
                notifications.append((holder_user["tg_id"], share_amount))
            company["cash_reserve"] = round(company["cash_reserve"] - payout_pool, 2)

    for tg_id, amount in notifications:
        if amount is None:
            await notify(bot, tg_id, "💤 Касса пуста, дивидендов сегодня нет.")
        else:
            await notify(bot, tg_id, f"💰 Дивиденды: {format_money(amount)} зачислены на ваш счёт в банке.")


def setup_scheduler(application) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def deposit_job():
        try:
            await capitalize_deposits(application.bot)
        except Exception:
            logger.exception("capitalize_deposits job failed")

    async def overdue_job():
        try:
            await check_overdue_tasks(application.bot)
        except Exception:
            logger.exception("check_overdue_tasks job failed")

    async def price_job():
        try:
            await recalc_price(application.bot)
        except Exception:
            logger.exception("recalc_price job failed")

    async def dividend_job():
        try:
            await pay_dividends(application.bot)
        except Exception:
            logger.exception("pay_dividends job failed")

    # All jobs are idempotent (guarded by a last-run date or per-user marker),
    # so a missed run, a duplicate fire, or a restart mid-day is harmless.
    scheduler.add_job(deposit_job, CronTrigger(hour=0, minute=5))
    scheduler.add_job(overdue_job, IntervalTrigger(minutes=10))
    scheduler.add_job(price_job, CronTrigger(hour=0, minute=10))
    scheduler.add_job(dividend_job, CronTrigger(hour=0, minute=15))
    scheduler.start()
    return scheduler
