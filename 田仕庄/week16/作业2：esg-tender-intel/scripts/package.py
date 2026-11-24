#!/usr/bin/env python3
"""打包入口（实现在 ``esgtender/package.py``）：按允许清单产出可分发的 zip。

    python scripts/package.py
    python scripts/package.py --list
"""

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from esgtender.package import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
