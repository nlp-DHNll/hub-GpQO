"""全局配置：模型参数、数据库路径与流程常量。

所有可调项集中在这里，方便换模型、换库、改重试次数而不用动实现代码。
"""
import os
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# 路径与环境
# ═══════════════════════════════════════════════════════════════════════════════

PROJECT_DIR = Path(__file__).resolve().parent      # .../week13/job1/sql_agent
JOB_DIR = PROJECT_DIR.parent                       # .../week13/job1

# 加载 .env（若存在且安装了 python-dotenv），环境变量优先级更高
try:
    from dotenv import load_dotenv
    load_dotenv(JOB_DIR / ".env")
except ImportError:  # 未安装 python-dotenv 时静默跳过
    pass

# ═══════════════════════════════════════════════════════════════════════════════
# 大模型配置（DeepSeek 兼容 OpenAI 协议，因此可直接用 langchain-openai 的 ChatOpenAI）
# ═══════════════════════════════════════════════════════════════════════════════

# API Key：老规矩，占位保留。优先级：运行时传入 > 环境变量 > 下面的占位符
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your_api_key")

# DeepSeek 接口地址，注意要带 /v1
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

# DeepSeek 必须显式指定模型名，不能用 OpenAI 的默认模型名
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

# 取 0 保证同一问题下 SQL 与审查结论稳定可复现
TEMPERATURE = 0.0

# ChatOpenAI 自带的重试次数（网络抖动 / 限流时指数退避重试）
LLM_MAX_RETRIES = 3

# ═══════════════════════════════════════════════════════════════════════════════
# 数据库配置
# ═══════════════════════════════════════════════════════════════════════════════

# chinook.db 放在 week11/job1 下，这里跨目录引用；可用环境变量 CHINOOK_DB 覆盖
DB_PATH = os.getenv(
    "CHINOOK_DB",
    str(JOB_DIR.parent.parent / "week11" / "job1" / "chinook.db"),
)

# SQLite 内置表，不作为业务表参与解析
INTERNAL_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_temp_master", "sqlite_master"}

# ═══════════════════════════════════════════════════════════════════════════════
# 流程控制
# ═══════════════════════════════════════════════════════════════════════════════

# 执行 SQL 后最多取回的行数，防止 prompt 被撑爆
MAX_RESULT_ROWS = 20

# 单个单元格值写进 prompt 时的最大展示长度
MAX_CELL_CHARS = 60

# “生成 -> 守卫 -> 审查 -> 修复”最多跑几轮
# 每轮内只允许原地修复 1 次：修复仍不过就直接进入下一轮重新生成，
# 避免在同一个错误方向上反复打转、白烧 API 调用
MAX_ROUNDS = 3

# ═══════════════════════════════════════════════════════════════════════════════
# 业务话术（确定性节点直接写死，保证文案永远一致）
# ═══════════════════════════════════════════════════════════════════════════════

# 不相关问题拒绝话术：由 refuse_node 直接输出，不经过 LLM
REFUSAL_ANSWER = "不在本智能体业务范围内，拒绝回答"
