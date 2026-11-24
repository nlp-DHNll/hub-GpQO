#!/usr/bin/env python3
"""兼容入口：命令行实现在 ``esgtender/cli.py``，编排在 ``esgtender/pipeline.py``。

保留这个文件是为了不让已经写进 cron / 文档里的
``python scripts/tender.py --days 30`` 失效。
"""

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from esgtender.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
