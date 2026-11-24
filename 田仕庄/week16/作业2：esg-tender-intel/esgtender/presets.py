"""行业预设：在 ``config/scope.yaml`` 之上做一次深合并。

为什么单独一层
--------------
``scope.yaml`` 是通用口径（ESG 咨询机构视角），但同一个 skill 被能源集团和
消费品牌拿去用时，关心的赛道完全不同——能源看重碳核查与绿电绿证，制造业看重
碳足迹与绿色工厂，上市公司看重报告编制与评级。把这些差异做成 preset，而不是
让用户每次改主配置（改完还会被下次升级覆盖）。

合并语义
--------
- 字典递归合并；
- **列表整段替换**（关键词表要的是「精确的新集合」，不是叠加——把通用关键词
  混进行业口径里，等于回到通用口径）；
- 标量覆盖。

因此 preset 里写到的列表必须写全，不能只写增量。这条写在每个 preset 的注释里，
避免后来者以为它是 append。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRESET_DIR = ROOT / "config" / "presets"


class PresetError(ValueError):
    """预设不存在或格式非法。"""


def list_presets(directory: Path | None = None) -> list[dict[str, Any]]:
    directory = directory or PRESET_DIR
    if not directory.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        items.append(
            {
                "name": path.stem,
                "title": data.get("title") or path.stem,
                "description": data.get("description") or "",
                "path": str(path),
            }
        )
    return items


def load_preset(name_or_path: str, directory: Path | None = None) -> dict[str, Any]:
    """按名字（``energy``）或路径加载预设，返回完整 preset 字典。"""
    directory = directory or PRESET_DIR
    candidate = Path(name_or_path)
    if candidate.suffix in {".yaml", ".yml"} or candidate.exists():
        path = candidate
    else:
        path = directory / f"{name_or_path}.yaml"
    if not path.exists():
        available = "、".join(item["name"] for item in list_presets(directory)) or "无"
        raise PresetError(f"找不到预设 {name_or_path!r}；可用：{available}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("scope"), dict):
        raise PresetError(f"预设 {path.name} 缺少 scope 段")
    data.setdefault("name", path.stem)
    data.setdefault("title", data.get("name"))
    data["path"] = str(path)
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """返回新字典：字典递归合并，列表/标量整体替换。不修改入参。"""
    merged: dict[str, Any] = dict(base)
    for key, value in (override or {}).items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            # 深拷贝一份，避免 preset 里的列表被下游原地修改后污染下一次调用
            merged[key] = _copy(value)
    return merged


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def apply_preset(scope: dict[str, Any], preset: dict[str, Any]) -> dict[str, Any]:
    """把 preset 的 ``scope`` 段合并进 scope。返回新字典，原 scope 不变。"""
    merged = deep_merge(scope, preset.get("scope") or {})
    preset_meta = {
        "name": preset.get("name"),
        "title": preset.get("title"),
        "description": preset.get("description") or "",
        "path": preset.get("path") or "",
    }
    merged["preset"] = preset_meta
    return merged
