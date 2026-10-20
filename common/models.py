"""Pure calculation helpers shared by both bots (no I/O)."""

from datetime import datetime, timezone


def parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def share_percentage(amount: int, total_shares: int) -> float:
    if total_shares <= 0:
        return 0.0
    return amount / total_shares * 100


def daily_deposit_interest(deposit: float, annual_rate: float) -> float:
    return deposit * annual_rate / 365.0


def vote_weights(db_shares: list, voter_ids: set) -> int:
    """Sum of share amounts for a set of tg_ids, using the shares table."""
    total = 0
    for s in db_shares:
        if s["tg_id"] in voter_ids:
            total += s["amount"]
    return total


def threshold_reached(weight: int, total_shares: int, threshold: float) -> bool:
    if total_shares <= 0:
        return False
    return weight > total_shares * threshold


def recalc_share_price(
    base_price: float,
    daily_profit: float,
    profit_baseline: float,
    overdue_count: int,
    open_task_count: int,
    k_profit: float,
    k_penalty: float,
) -> float:
    """share_price = base_price * (1 + k_profit*profit_factor) * (1 - k_penalty*penalty_factor)."""
    profit_factor = 0.0
    if profit_baseline > 0:
        profit_factor = max(-1.0, min(2.0, daily_profit / profit_baseline))

    penalty_factor = 0.0
    if open_task_count > 0:
        penalty_factor = min(1.0, overdue_count / open_task_count)
    elif overdue_count > 0:
        penalty_factor = 1.0

    price = base_price * (1 + k_profit * profit_factor) * (1 - k_penalty * penalty_factor)
    return max(1.0, round(price, 2))
