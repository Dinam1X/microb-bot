"""Matplotlib share-price chart rendering."""

import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common.db import BASE_DIR

CHART_DIR = BASE_DIR / "data" / "charts"


def render_price_chart(price_history: list, ticker: str) -> str:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    history = price_history[-30:]
    dates = [p["date"][5:] for p in history]
    prices = [p["price"] for p in history]

    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
    ax.plot(dates, prices, color="#2e8b57", linewidth=2, marker="o", markersize=3)
    ax.fill_between(range(len(dates)), prices, min(prices) * 0.98 if prices else 0, color="#2e8b57", alpha=0.08)
    ax.set_title(f"{ticker} — цена акции (30 дней)")
    ax.set_ylabel("₽")
    ax.grid(True, alpha=0.3)
    step = max(1, len(dates) // 10)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels(dates[::step], rotation=45, ha="right")
    fig.tight_layout()

    tmp = tempfile.NamedTemporaryFile(dir=CHART_DIR, suffix=".png", delete=False)
    fig.savefig(tmp.name)
    plt.close(fig)
    return tmp.name
