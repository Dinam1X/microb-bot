"""JSON database for the bot (bank + company features in one process).

All mutation goes through the ``transaction()`` context manager, which takes
a file lock and an in-process thread lock, then does read -> yield -> write,
so concurrent handlers never tear each other's writes.
"""

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "db.json"
LOCK_PATH = DATA_DIR / "db.json.lock"

DEFAULT_SETTINGS = {
    "deposit_rate_annual": 0.10,
    "dividend_rate": 0.30,
    "task_reward_multiplier": 1.0,
    "penalty_multiplier": 0.5,
    "penalty_reset_tasks": 3,
    "k_profit": 0.5,
    "k_penalty": 0.3,
    "task_vote_threshold": 0.5,
    "issue_vote_threshold": 0.51,
    "price_profit_baseline": 1000.0,
    "base_price": 100.0,
}

ROLES = ["CEO", "CMO", "CFO", "CTO", "COO", "Сотрудник", "Другое"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _default_db() -> dict:
    return {
        "users": [],
        "shares": [],
        "company": {
            "name": "ПАО МикРоб",
            "ticker": "MICROB",
            "total_shares": 1000,
            "share_price": 100.0,
            "cash_reserve": 0.0,
            "last_dividend_at": None,
            "last_price_update_at": None,
            "penalty_active": False,
            "consecutive_success_count": 0,
            "daily_profit": 0.0,
            "daily_overdue_count": 0,
            "price_history": [{"date": today_str(), "price": 100.0}],
        },
        "tasks": [],
        "votes": [],
        "transactions": [],
        "settings": dict(DEFAULT_SETTINGS),
    }


def _migrate(data: dict) -> dict:
    default = _default_db()
    for key, val in default.items():
        if key not in data:
            data[key] = val
    for key, val in default["company"].items():
        data["company"].setdefault(key, val)
    for key, val in DEFAULT_SETTINGS.items():
        data["settings"].setdefault(key, val)
    for user in data["users"]:
        user.setdefault("cash", 0.0)
        user.setdefault("deposit", 0.0)
        user.setdefault("deposit_opened_at", None)
        user.setdefault("deposit_interest_accrued", 0.0)
        user.setdefault("deposit_last_capitalized_at", None)
        user.setdefault("created_at", now_iso())
    return data


_thread_lock = threading.RLock()
_file_lock = FileLock(str(LOCK_PATH))


def _read_raw() -> dict:
    if not DB_PATH.exists():
        return _default_db()
    with open(DB_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return _default_db()
    return _migrate(json.loads(content))


def _write_raw(data: dict) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DB_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DB_PATH)


@contextmanager
def transaction():
    """Atomic read -> modify -> write transaction over db.json.

    Usage::

        with transaction() as db:
            user = get_user(db, tg_id)
            user["cash"] += 100
    """
    with _thread_lock:
        with _file_lock:
            data = _read_raw()
            yield data
            _write_raw(data)


def load() -> dict:
    """Read-only snapshot of the database."""
    with _thread_lock:
        with _file_lock:
            return _read_raw()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(db: dict, tg_id: int) -> dict | None:
    for u in db["users"]:
        if u["tg_id"] == tg_id:
            return u
    return None


def is_registered(tg_id: int) -> bool:
    return get_user(load(), tg_id) is not None


def all_users(db: dict) -> list:
    return db["users"]


def other_users(db: dict, tg_id: int) -> list:
    return [u for u in db["users"] if u["tg_id"] != tg_id]


def create_user(db: dict, tg_id: int, name: str, role: str) -> dict:
    """Register a new user. The first two registrants get 500 shares each."""
    user = {
        "tg_id": tg_id,
        "name": name,
        "role": role,
        "cash": 10000.0,
        "deposit": 0.0,
        "deposit_opened_at": None,
        "deposit_interest_accrued": 0.0,
        "deposit_last_capitalized_at": None,
        "created_at": now_iso(),
    }
    db["users"].append(user)

    existing_holders = [s for s in db["shares"] if s["amount"] > 0]
    if len(db["users"]) <= 2:
        db["shares"].append({"tg_id": tg_id, "amount": 500})
    else:
        db["shares"].append({"tg_id": tg_id, "amount": 0})
    return user


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------

def get_shares(db: dict, tg_id: int) -> int:
    for s in db["shares"]:
        if s["tg_id"] == tg_id:
            return s["amount"]
    return 0


def set_shares(db: dict, tg_id: int, amount: int) -> None:
    for s in db["shares"]:
        if s["tg_id"] == tg_id:
            s["amount"] = amount
            return
    db["shares"].append({"tg_id": tg_id, "amount": amount})


def add_shares(db: dict, tg_id: int, delta: int) -> None:
    set_shares(db, tg_id, get_shares(db, tg_id) + delta)


def total_shares_outstanding(db: dict) -> int:
    return sum(s["amount"] for s in db["shares"])


def shareholders(db: dict) -> list:
    """List of (user, amount) for everyone holding at least one share."""
    result = []
    for s in db["shares"]:
        if s["amount"] > 0:
            user = get_user(db, s["tg_id"])
            if user:
                result.append((user, s["amount"]))
    result.sort(key=lambda pair: pair[1], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def add_transaction(
    db: dict,
    type_: str,
    amount: float,
    from_id: int | None = None,
    to_id: int | None = None,
    description: str = "",
) -> dict:
    tx = {
        "id": new_id("tx"),
        "type": type_,
        "amount": amount,
        "from_id": from_id,
        "to_id": to_id,
        "description": description,
        "created_at": now_iso(),
    }
    db["transactions"].append(tx)
    return tx


def user_transactions(db: dict, tg_id: int) -> list:
    txs = [
        tx
        for tx in db["transactions"]
        if tx.get("from_id") == tg_id or tx.get("to_id") == tg_id
    ]
    txs.sort(key=lambda t: t["created_at"], reverse=True)
    return txs


def company_transactions(db: dict) -> list:
    types = {"profit", "dividend", "share_transfer", "task_penalty"}
    txs = [tx for tx in db["transactions"] if tx["type"] in types]
    txs.sort(key=lambda t: t["created_at"], reverse=True)
    return txs


# ---------------------------------------------------------------------------
# Company / settings
# ---------------------------------------------------------------------------

def get_company(db: dict) -> dict:
    return db["company"]


def get_settings(db: dict) -> dict:
    return db["settings"]
