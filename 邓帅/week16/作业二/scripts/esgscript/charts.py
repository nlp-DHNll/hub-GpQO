"""图表：把统计结果画成图（仅脚本版出图）。中文需要显式指定字体。"""

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from . import config  # noqa: E402

CHARTS_DIR = "charts"


def _use_chinese_font() -> None:
    font_manager.fontManager.addfont(config.FONT_PATH)
    name = font_manager.FontProperties(fname=config.FONT_PATH).get_name()
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [name]
    plt.rcParams["axes.unicode_minus"] = False


def _barh(labels: list[str], values: list[float], title: str, path: Path, *, unit: str = "") -> None:
    """横向条形图：标签在纵轴，条上标数值。"""
    figure, axis = plt.subplots(figsize=(8, 0.6 * len(labels) + 1.6), dpi=144)
    positions = range(len(labels))
    axis.barh(positions, values, color="#2f6f9f")
    axis.set_yticks(list(positions), labels)
    axis.invert_yaxis()
    axis.set_title(title)
    axis.spines[["top", "right"]].set_visible(False)
    for position, value in zip(positions, values, strict=True):
        axis.text(value, position, f" {value:g}{unit}", va="center", fontsize=9)
    axis.set_xlim(0, max(values) * 1.18 if values else 1)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def _trend(periods: list[str], counts: list[float], title: str, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(8, 4), dpi=144)
    axis.bar(periods, counts, color="#c0504d")
    axis.set_title(title)
    axis.spines[["top", "right"]].set_visible(False)
    axis.tick_params(axis="x", labelsize=9)
    for position, value in enumerate(counts):
        axis.text(position, value, f" {value:g}", ha="center", va="bottom", fontsize=9)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_bid_charts(stats: dict[str, Any], out_dir: Path) -> list[str]:
    """按统计结果出四张图：热点主题、金额分布、趋势、地区分布。返回相对运行目录的路径。"""
    _use_chinese_font()
    charts_dir = out_dir / CHARTS_DIR
    charts_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    rank = [item for item in stats["topic_rank"] if item["topic"] != "未标注"][:10]
    if rank:
        path = charts_dir / "topic_rank.png"
        _barh(
            [item["topic"] for item in rank], [item["count"] for item in rank], "热点主题排行（样本数）", path
        )
        written.append(f"{CHARTS_DIR}/topic_rank.png")

    buckets = [item for item in stats["amount_distribution"] if item["count"]]
    if buckets:
        path = charts_dir / "amount_distribution.png"
        _barh(
            [item["bucket"] for item in buckets],
            [item["count"] for item in buckets],
            "中标金额分布（样本数）",
            path,
        )
        written.append(f"{CHARTS_DIR}/amount_distribution.png")

    trend = stats["trend"]
    if trend:
        path = charts_dir / "trend.png"
        _trend(
            [item["period"] for item in trend],
            [item["count"] for item in trend],
            "中标公告数的时间趋势",
            path,
        )
        written.append(f"{CHARTS_DIR}/trend.png")

    regions = list(stats["regions"].items())[:12]
    if regions:
        path = charts_dir / "region.png"
        _barh([name for name, _ in regions], [count for _, count in regions], "地区分布（样本数）", path)
        written.append(f"{CHARTS_DIR}/region.png")
    return written
