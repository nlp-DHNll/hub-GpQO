"""引导模块：在不安装原 agents SDK 的前提下，安全复用原 sql_agent 包。

原 sql_agent 包 __init__ 会顺带导入 workflow / agents SDK。复刻版不依赖该 SDK，
这里用一个轻量桩对象替掉 `agents` 模块，使原包可被正常 import
（workflow / agents 模块虽被加载，但不会被调用）。
请在 import 任何 `sql_agent.*` 之前先 `import _bootstrap`。
"""

from __future__ import annotations

import contextlib
import sys
import types
from pathlib import Path

# 支持在项目根目录放置 .env 文件来配置密钥，免去每次手动设置环境变量。
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # noqa: BLE001 - 没装 python-dotenv 或没有 .env 时忽略
    pass


def _install_stub() -> None:
    if "agents" in sys.modules:
        return

    class _Agent:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name")
            self.model = kwargs.get("model")
            self.instructions = kwargs.get("instructions")
            self.model_settings = kwargs.get("model_settings")
            self.output_type = kwargs.get("output_type")

    class _ModelSettings:
        def __init__(self, *args, **kwargs):
            self.temperature = kwargs.get("temperature", 0.0)

    stub = types.ModuleType("agents")
    stub.Runner = object()
    stub.trace = lambda *a, **k: contextlib.nullcontext()
    stub.Agent = _Agent
    stub.ModelSettings = _ModelSettings
    stub.set_default_openai_api = lambda *a, **k: None
    stub.set_tracing_disabled = lambda *a, **k: None
    sys.modules["agents"] = stub


def add_original_src_to_path() -> None:
    original_src = (
        Path(__file__).resolve().parents[2]
        / "Week12_2026Q2"
        / "week11"
        / "task1"
        / "00-sql-agent"
        / "src"
    )
    if str(original_src) not in sys.path:
        sys.path.insert(0, str(original_src))


_install_stub()
add_original_src_to_path()
