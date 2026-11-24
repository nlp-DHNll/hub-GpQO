#!/usr/bin/env python3
"""每日增量入口：给 cron / 计划任务用的薄包装。

做的事只有三件：
1. 默认参数改成「近 2 天 + 只报新增 + 去重库 + 清理」——日常监控的合理口径：
   2 天覆盖时区与发布延迟，``--only-new`` 保证报告与推送里只有新项目；
2. 如果环境里配了 ``NOTIFY_WEBHOOK_URL`` 而用户没显式指定 ``--notify``，自动推送；
3. 其余参数原样透传给 CLI，用户显式给的值会覆盖上面的默认值
   （argparse 取最后一次出现的值，所以默认值放在前面）。

用法::

    python scripts/daily.py                    # 近 2 天，仅新增，自动推送（若已配置）
    python scripts/daily.py --days 7           # 改窗口
    python scripts/daily.py --no-store         # 临时退回全量快照
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from esgtender import cli  # noqa: E402
from esgtender import notify as notify_mod  # noqa: E402

DEFAULTS = ["--days", "2", "--incremental", "--only-new", "--limit", "30", "--prune-days", "730"]


def build_argv(argv: list[str] | None = None) -> list[str]:
    user = list(sys.argv[1:] if argv is None else argv)
    merged = list(DEFAULTS) + user
    if not any(item == "--notify" or item.startswith("--notify=") for item in user):
        env = notify_mod.load_env()
        if env.get("NOTIFY_WEBHOOK_URL") or env.get("WEBHOOK_URL"):
            merged += ["--notify", "webhook"]
        elif env.get("SMTP_HOST") and env.get("SMTP_TO"):
            merged += ["--notify", "email"]
    return merged


def main(argv: list[str] | None = None) -> int:
    return cli.main(build_argv(argv))


if __name__ == "__main__":
    raise SystemExit(main())
