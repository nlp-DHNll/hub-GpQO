"""esgjudge 的单元测试：抓页与模型全部打桩，不打真网络、不调真模型、不读 .env。"""

from __future__ import annotations

import json
from pathlib import Path

import esgjudge as ej


def make_run(
    tmp_path: Path,
    name: str,
    evidence: list[dict] | None = None,
    records: list[dict] | None = None,
    window: tuple[str, str] = ("2026-11-20", "2026-11-26"),
    report: str = "# 报告\n",
) -> Path:
    """在 tmp_path 下造一个最小运行目录：三件产物齐全。"""
    run_dir = tmp_path / name
    run_dir.mkdir()
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    payload = {"evidence": evidence} if evidence is not None else {"records": records}
    (run_dir / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps({"time_window": {"start": window[0], "end": window[1]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return run_dir


def ev(
    num: int,
    url: str = "https://example.com/a",
    published: str | None = "2026-11-21",
    quote: str = "示例摘录",
    section: str = "政策/评级/标准动态",
    verification: str = "verified",
) -> dict:
    return {
        "id": num,
        "section": section,
        "claim": f"结论{num}",
        "url": url,
        "published_at": published,
        "quote": quote,
        "credibility_tier": 2,
        "verification": verification,
    }


def fake_judge_complete(prompt: str) -> str:
    """按报告内容打分的假评委：含 ALPHA 的报告得 9 分、含 BETA 的得 6 分，与出现顺序无关。"""
    by_marker = {"ALPHA": 9, "BETA": 6}
    first_marker = min((prompt.find(marker), marker) for marker in by_marker)[1]
    second_marker = next(marker for marker in by_marker if marker != first_marker)
    payload = {}
    for label, marker in (("甲", first_marker), ("乙", second_marker)):
        payload[label] = {
            dim: {"score": by_marker[marker], "reason": f"{marker}-{dim}"} for dim in ej.DIMENSIONS
        }
    return json.dumps(payload, ensure_ascii=False)


# ---- trace：quote 是子串时不调模型 ----


def test_substring_quote_skips_model(tmp_path):
    page = "正文：矿井用电平均单价降至0.6917元/千瓦时，同比下降。"
    run = make_run(tmp_path, "r1", evidence=[ev(1, quote="矿井用电平均单价降至0.6917元/千瓦时")])
    model_calls: list[str] = []

    def fake_complete(prompt: str) -> str:
        model_calls.append(prompt)
        return "yes"

    ej.cmd_trace(
        [run],
        tmp_path / "out.json",
        limit=0,
        fetch=lambda url: (True, page, None),
        complete=fake_complete,
    )
    assert model_calls == []  # 子串直接判支持，不该调模型
    item = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["runs"][0]["items"][0]
    assert item["supported"] is True
    assert item["support_how"] == "substring"
    assert item["traceable"] is True


# ---- trace：日期未知的归类与分母 ----


def test_unknown_date_out_of_window_denominator(tmp_path):
    evidence = [
        ev(1, url="https://example.com/1", published=None, quote="甲"),
        ev(2, url="https://example.com/2", published="2026-11-21", quote="乙"),
        ev(3, url="https://example.com/3", published="2026-11-01", quote="丙"),
    ]
    run = make_run(tmp_path, "r2", evidence=evidence)
    page = "正文：甲乙丙都有。"
    ej.cmd_trace(
        [run],
        tmp_path / "out.json",
        limit=0,
        fetch=lambda url: (True, page, None),
        complete=lambda prompt: "yes",
    )
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["runs"][0]
    statuses = {item["id"]: item["date_status"] for item in result["items"]}
    assert statuses == {1: "unknown", 2: "in_window", 3: "out_of_window"}
    assert result["counts"]["unknown_date"] == 1
    assert result["counts"]["date_known"] == 2  # 日期未知不计入落窗分母
    assert result["rates"]["in_window_rate"] == 0.5
    assert result["items"][0]["traceable"] is False  # 日期未知即不可溯源


# ---- trace：缓存复用，重跑不联网、不调模型 ----


def test_trace_cache_reuse(tmp_path):
    page = "正文内容不含摘录原文。"
    run = make_run(tmp_path, "r3", evidence=[ev(1, published="2026-11-21", quote="这句不在正文里")])
    calls = {"fetch": 0, "complete": 0}

    def fake_fetch(url: str):
        calls["fetch"] += 1
        return True, page, None

    def fake_complete(prompt: str) -> str:
        calls["complete"] += 1
        return "yes"

    ej.cmd_trace([run], tmp_path / "o1.json", limit=0, fetch=fake_fetch, complete=fake_complete)
    assert calls == {"fetch": 1, "complete": 1}
    assert (run / "trace.json").exists()

    ej.cmd_trace([run], tmp_path / "o2.json", limit=0, fetch=fake_fetch, complete=fake_complete)
    assert calls == {"fetch": 1, "complete": 1}  # 第二遍全部复用缓存
    item = json.loads((tmp_path / "o2.json").read_text(encoding="utf-8"))["runs"][0]["items"][0]
    assert item["supported"] is True
    assert item["support_how"] == "cache"


# ---- judge：两遍换序的均值与对齐 ----


def scores_all(score: int) -> dict:
    return {dim: {"score": score, "reason": f"理由{score}"} for dim in ej.DIMENSIONS}


def test_aggregate_aligns_swapped_rounds():
    first = {"甲": scores_all(9), "乙": scores_all(6)}  # 第一遍：甲=目录 A，乙=目录 B
    second = {"甲": scores_all(6), "乙": scores_all(9)}  # 第二遍换序：甲=目录 B，乙=目录 A
    agg = ej.aggregate_scores(first, second)
    assert agg["a"]["total"] == 9  # 目录 A 两遍都得 9：第一遍的甲与第二遍的乙
    assert agg["b"]["total"] == 6
    assert agg["a"]["scores"]["结构完整"]["round1"] == 9
    assert agg["a"]["scores"]["结构完整"]["round2"] == 9
    assert agg["a"]["scores"]["结构完整"]["mean"] == 9


def test_judge_two_rounds_with_fake_model(tmp_path):
    dir_a = make_run(tmp_path, "alpha", evidence=[ev(1, url="https://example.com/1")], report="ALPHA 正文")
    dir_b = make_run(tmp_path, "beta", evidence=[ev(1, url="https://example.com/2")], report="BETA 正文")
    result = ej.run_judge(dir_a, dir_b, limit=10, complete=fake_judge_complete)
    assert result["a"]["total"] == 9
    assert result["b"]["total"] == 6
    assert result["a"]["scores"]["准确性"]["round2"] == 9  # 第二遍 ALPHA 排在乙位，对齐后仍归目录 A
    assert result["rounds"] == [
        {"round": 1, "甲": str(dir_a.resolve()), "乙": str(dir_b.resolve())},
        {"round": 2, "甲": str(dir_b.resolve()), "乙": str(dir_a.resolve())},
    ]


# ---- judge：模型输出解析失败重试与彻底失败 ----


def test_ask_judge_retries_then_succeeds():
    calls: list[str] = []

    def flaky(prompt: str) -> str:
        calls.append(prompt)
        return "不是 JSON 的回答" if len(calls) == 1 else fake_judge_complete(prompt)

    parsed = ej.ask_judge("提示词", flaky)
    assert len(calls) == 2  # 第一次解析失败重试了一次
    assert parsed["甲"]["结构完整"]["score"] == 9


def test_ask_judge_gives_up_after_attempts():
    calls: list[str] = []

    def always_bad(prompt: str) -> str:
        calls.append(prompt)
        return "不是 JSON"

    try:
        ej.ask_judge("提示词", always_bad, attempts=3)
    except SystemExit as exc:
        assert "解析失败" in str(exc)
    assert len(calls) == 3  # 首次 + 最多 2 次重试


# ---- 模型名解析：大小写不敏感 ----


class _FakeModels:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    def list(self):
        from types import SimpleNamespace

        return [SimpleNamespace(id=model_id) for model_id in self._ids]


class _FakeClient:
    def __init__(self, ids: list[str]) -> None:
        self.models = _FakeModels(ids)


def test_resolve_model_id_case_insensitive():
    client = _FakeClient(["glm-5.3", "qwen3.8-flash", "deepseek-v4"])
    assert ej.resolve_model_id(client, "qwen3.8-Flash") == "qwen3.8-flash"
    assert ej.resolve_model_id(client, "GLM-5.3") == "glm-5.3"
    assert ej.resolve_model_id(client, "qwen3.8-flash") == "qwen3.8-flash"  # 精确一致原样返回
    assert ej.resolve_model_id(client, "不存在的模型") == "不存在的模型"  # 找不到原样返回


def test_resolve_model_id_list_failure_falls_back():
    class _Broken:
        class models:  # noqa: N801
            @staticmethod
            def list():
                raise RuntimeError("列表拉取失败")

    assert ej.resolve_model_id(_Broken(), "qwen3.8-Flash") == "qwen3.8-Flash"


# ---- calibrate：方向判断 ----


def test_calibrate_direction():
    assert ej.direction_ok(8.2, 6.1) is True
    assert ej.direction_ok(6.1, 8.2) is False
    assert ej.direction_ok(7.0, 7.0) is False  # 持平也算方向不对


def test_calibrate_end_to_end(tmp_path):
    good = make_run(tmp_path, "good", evidence=[ev(1, url="https://example.com/1")], report="报告正文 ALPHA")
    bad = make_run(tmp_path, "bad", evidence=[ev(1, url="https://example.com/2")], report="报告正文 BETA")
    assert ej.cmd_calibrate(good, bad, limit=10, complete=fake_judge_complete) == 0  # 好的更高 → 通过
    assert ej.cmd_calibrate(bad, good, limit=10, complete=fake_judge_complete) == 1  # 反传 → 非零退出
