"""脚本版：把检索、抓取、筛选、总结、统计、图表、渲染、核验沉淀为确定性脚本。

导入本包时先把脚本目录接进 sys.path——运行产物契约与验收器在同级的 esgtools 包里，两版共用一份。
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
