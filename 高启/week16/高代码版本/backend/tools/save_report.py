"""保存通过评价的报告，并保留之前生成的版本。"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def save_report(month: str, markdown: str, directory: Path) -> Path:
    """先完整写入临时文件，再在同一目录下发布 Markdown。"""
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"{month}-{timestamp}-{uuid4().hex}.md"
    temporary = target.with_suffix(".tmp")

    stream = temporary.open("x", encoding="utf-8", newline="\n")
    try:
        with stream:
            stream.write(markdown.rstrip() + "\n")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
