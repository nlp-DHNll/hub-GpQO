"""配置读取：全项目唯一入口，只暴露白名单里的键。

为什么不是「读 .env + 合并 os.environ」
--------------------------------------
``notify.load_env()`` 早期实现是 ``env.update(os.environ)``——把**进程的全部
环境变量**（含 ``GITHUB_TOKEN``、``AWS_*``、``DATABASE_URL``）交给调用方。
这类实现平时看不出问题，直到某次「为了排错把 env 写进 run_meta」就变成泄密。

凭据的读取面必须比「进程环境」小：只有这里点名的键能被读出来，新增通道时
在 ``ALLOWED_KEYS`` 加一行即可，不需要改调用方。
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "config" / ".env"

# 允许从 .env / 环境变量读取的键。多一个键就多一份风险，别把不相关的塞进来。
ALLOWED_KEYS = (
    "BOCHA_API_KEY",
    "BOCHA_ENDPOINT",
    "NOTIFY_WEBHOOK_URL",
    "WEBHOOK_URL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_TO",
)


def _tighten_permissions(path: Path) -> None:
    """POSIX 下把 .env 收紧到 0600；Windows 无对应语义，直接跳过。"""
    if os.name != "posix" or not path.exists():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if not mode & 0o077:  # 同组/其他用户都不可读，已合规
        return
    try:
        path.chmod(0o600)
    except OSError:
        return
    print(
        f"[警告] {path} 权限 {oct(mode)} 过宽（同机其他用户可读），已收紧为 0o600",
        file=sys.stderr,
    )


def load_env(path: Path | None = None, *, extra: tuple[str, ...] = ()) -> dict[str, str]:
    """读 ``.env`` 并叠加进程环境变量，只返回白名单内的键。

    进程环境变量优先于文件值（cron / CI 里覆盖配置的常规做法）。
    """
    path = path or ENV_PATH
    allowed = set(ALLOWED_KEYS) | set(extra)
    env: dict[str, str] = {}

    if path.exists():
        _tighten_permissions(path)
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            if key not in allowed:
                continue  # 白名单外的键直接丢弃，不进入返回值
            env[key] = val.split(" #", 1)[0].strip().strip('"').strip("'")

    env.update({key: os.environ[key] for key in allowed if key in os.environ})
    return env
