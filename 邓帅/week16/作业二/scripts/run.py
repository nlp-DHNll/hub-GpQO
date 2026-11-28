#!/usr/bin/env python
"""脚本版入口：在任意工作目录下都能运行。

    python run.py collect --case monthly-report --client 中国神华 --industry 煤炭·能源\
        --days 30 --budget 20 --out <运行目录>
    python run.py build --out <运行目录>

每条子命令都是「参数进、JSON 出」；esgtools 是两版共用的运行产物契约与验收器。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from esgscript.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
