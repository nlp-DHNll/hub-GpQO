#!/usr/bin/env python3
"""按**允许清单**打包 skill，产出可分发的 zip。

为什么不是「排除清单」
----------------------
上一版是在命令行里写 ``EXCLUDE_DIRS = {cache, output, data}`` + ``.env``。
排除清单的语义是「默认全带」——漏一条就泄一个 ``.env``，而这类脚本恰恰
不会进代码评审。允许清单反过来：默认什么都不带，只带这里点名的路径。

用法::

    python scripts/package.py                       # → dist/esg-tender-intel.zip
    python scripts/package.py --out /tmp/x.zip
    python scripts/package.py --list                # 只列文件，不打包
"""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
# 产物放在 skill 目录**外**（skills/dist/）：构建产物不该混进 skill 自身，
# 否则下次打包 / 分发时容易把它一起带上。
DIST_DIR = ROOT.parent / "dist"
PKG_NAME = "esg-tender-intel"

# 只有这里列出的路径会进包。新增目录记得加（例如将来加 docs/）。
ALLOW = (
    "SKILL.md",
    "requirements.txt",
    ".gitignore",
    "config/scope.yaml",
    "config/sources.yaml",
    "config/.env.example",
    "config/presets/",
    "esgtender/",
    "scripts/",
    "templates/",
    "references/",
    "fixtures/",
    "tests/",
    "deploy/",
)

# 允许目录里仍然要挡掉的运行态残留（目录名或文件名精确匹配）
DENY_DIR_PARTS = {"cache", "output", "data", "__pycache__", ".pytest_cache", ".venv", "logs"}
DENY_NAMES = {".env"}


def _blocked(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in DENY_DIR_PARTS for part in rel.parts):
        return True
    if path.name in DENY_NAMES:
        return True
    return path.suffix in {".pyc", ".tmp"}


def iter_files(root: Path = ROOT) -> list[Path]:
    """按允许清单展开成文件列表（去重、排序）。"""
    found: set[Path] = set()
    for entry in ALLOW:
        target = root / entry
        if target.is_dir():
            found.update(
                path for path in target.rglob("*") if path.is_file() and not _blocked(path, root)
            )
        elif target.is_file() and not _blocked(target, root):
            found.add(target)
    return sorted(found)


def package(out: Path, root: Path = ROOT) -> tuple[Path, list[Path]]:
    files = iter_files(root)
    if not files:
        raise SystemExit(f"允许清单没有命中任何文件，检查 ROOT：{root}")
    missing = [entry for entry in ALLOW if not (root / entry).exists()]
    if missing:
        # 清单里有、实际不存在的条目多半是改名后忘同步，提示但不失败
        print(f"[提示] 允许清单里这些路径不存在：{'、'.join(missing)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{PKG_NAME}/{path.relative_to(root).as_posix()}")
    return out, files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按允许清单把 skill 打成 zip（默认不含 .env / cache / output）。")
    parser.add_argument(
        "--out", default=str(DIST_DIR / f"{PKG_NAME}.zip"), help="输出 zip 路径"
    )
    parser.add_argument("--list", action="store_true", help="只列出将被打包的文件")
    args = parser.parse_args(argv)

    if args.list:
        for path in iter_files():
            print(path.relative_to(ROOT).as_posix())
        return 0

    target, files = package(Path(args.out))
    print(f"打包完成：{target}（{len(files)} 个文件，{target.stat().st_size / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
