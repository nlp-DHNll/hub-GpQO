"""路径引导：让作业二可以直接 import 作业一里的 ``sql_agent_lg``。

两个目录必须保持兄弟关系：

    week13/
    ├── 作业一/sql_agent_lg/
    └── 作业二/backend/

这样不需要把作业一的代码复制一份，也不需要先 ``pip install -e``。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]          # 作业二/
AGENT_ROOT = PROJECT_ROOT.parent / "作业一"                  # 作业一/
STATIC_DIR = PROJECT_ROOT / "static"

if not AGENT_ROOT.exists():  # pragma: no cover - 目录被单独拷贝时才触发
    raise RuntimeError(
        f"找不到作业一目录：{AGENT_ROOT}\n"
        "请把 week13/作业一 和 week13/作业二 放在同一个目录下。"
    )

if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))
