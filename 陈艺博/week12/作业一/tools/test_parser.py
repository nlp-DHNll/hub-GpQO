"""解析器单元测试：确认模型返回的各种脏格式都能被兜住。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import llm  # noqa: E402

CASES = [
    (
        "标准 JSON",
        '{"is_corridor":true,"risk_level":"中风险","risk_score":52,"hazards":[{"name":"纸箱","category":"可燃堆积物","severity":"中"}],"evidence":"画面左侧堆纸箱","confidence":0.8}',
        ("中风险", 52, 1),
    ),
    (
        "```json 围栏",
        '```json\n{"is_corridor":true,"risk_level":"高风险","risk_score":90,"hazards":[{"name":"电动车"}],"evidence":"右侧"}\n```',
        ("高风险", 90, 1),
    ),
    (
        "前后带废话",
        '好的，我的判断如下：{"risk_level":"高风险","is_corridor":true,"risk_score":88,"evidence":"右侧电动车"} 以上。',
        ("高风险", 88, 0),
    ),
    (
        "等级写简称 + 分数是字符串",
        '{"risk_level":"高","is_corridor":true,"risk_score":"91","hazards":["电动车"]}',
        ("高风险", 91, 1),
    ),
    (
        "非楼道",
        '{"is_corridor":false,"risk_level":"非楼道","evidence":"办公室桌面"}',
        ("非楼道", 0, 0),
    ),
    (
        "纯文本无 JSON",
        "这张图看起来是楼道，有一些杂物，大概中等风险。",
        ("中风险", 55, 0),
    ),
    (
        "越界数值",
        '{"risk_level":"无风险","risk_score":-5,"hazards":[],"confidence":1.7,"blocked_passage":"false"}',
        ("无风险", 0, 0),
    ),
    (
        "英文等级",
        '{"risk_level":"high","is_corridor":true,"risk_score":75,"evidence":"e-bike"}',
        ("高风险", 75, 0),
    ),
]

ok = 0
for name, text, expect in CASES:
    r = llm.parse_result(text)
    got = (r["risk_level"], r["risk_score"], len(r["hazards"]))
    flag = "PASS" if got == expect else "FAIL"
    if got == expect:
        ok += 1
    print(f"[{flag}] {name:<18} -> {got}  (期望 {expect})  parse_ok={r['parse_ok']}")

print(f"\n{ok}/{len(CASES)} 通过")
