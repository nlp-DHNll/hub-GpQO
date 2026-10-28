# -*- coding: utf-8 -*-
"""离线自测：图片归一化、风险类别归一化、模型输出解析。运行：python tools/self_test.py"""

import io
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import llm
from prompt import parse_response, normalize_category


def _tiny_image_b64(color=(200, 90, 90)):
    from PIL import Image
    img = Image.new("RGB", (320, 240), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
            print(f"  [FAIL] {name} {detail}")
        else:
            print(f"  [PASS] {name}")

    print("== 1. 图片归一化 ==")
    url, nbytes = llm.normalize_image(_tiny_image_b64(), max_edge=1568, quality=85)
    check("data URL 前缀与 JPEG 编码", url.startswith("data:image/jpeg;base64,") and nbytes > 0)
    check("超大图片被拒绝", _try(lambda: llm.normalize_image("data:image/jpeg;base64," + "A" * 200), llm.ImageError))
    check("非法 base64 被拒绝", _try(lambda: llm.normalize_image("!!not-base64!!"), llm.ImageError))

    print("== 2. 风险类别归一化 ==")
    for raw, want in [
        ("高风险", "高风险"), ("危", "高风险"), ("中等风险", "中风险"), ("中", "中风险"),
        ("低风险", "低风险"), ("无隐患", "无风险"), ("无风险", "无风险"),
        ("非楼道", "非楼道"), ("这张图不是楼道", "非楼道"), ("中风险，楼道堆物", "中风险"),
    ]:
        check(f"normalize({raw!r})", normalize_category(raw) == want, f"-> {normalize_category(raw)}")

    print("== 3. 模型输出解析 ==")
    good = '{"category": "高风险", "reason": "楼道内停放电动车并飞线充电"}'
    cat, reason = parse_response(good)
    check("标准 JSON", cat == "高风险" and "电动车" in reason)

    fenced = '```json\n{"category":"中风险","reason":"大量纸箱堆积"}\n```'
    cat, reason = parse_response(fenced)
    check("带代码块围栏", cat == "中风险")

    noise = '好的，判断如下：{"category": "无风险", "reason": "楼道干净整洁，无堆放物品"} 完毕。'
    cat, reason = parse_response(noise)
    check("前后夹杂解释文字", cat == "无风险")

    plain = "中风险，楼道堆放大量木家具"
    cat, _ = parse_response(plain)
    check("无 JSON 兜底", cat == "中风险")

    print("== 4. 演示模式 ==")
    spec = {}
    r = llm.classify("mock", _tiny_image_b64(), spec, "")
    check("mock 返回五档之一", r["category"] in ("高风险", "中风险", "低风险", "无风险", "非楼道"))

    print(f"\n结果：{'全部通过' if failed == 0 else f'{failed} 项失败'}")
    sys.exit(1 if failed else 0)


def _try(fn, exc_type):
    try:
        fn()
        return False
    except exc_type:
        return True


if __name__ == "__main__":
    main()
