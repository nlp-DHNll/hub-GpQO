"""识别接口用例(技术设计 §4.3 八条;mock 边界=app.llm.recognize_image,T2)。"""
import base64

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError, OpenAIError

from app import llm
from app.main import app

client = TestClient(app)

# 1px PNG,合规最小图片
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)


def _mock(monkeypatch, outputs: str | list[str] | None = None, error: Exception | None = None):
    """替换 llm.recognize_image,记录调用次数并按序返回/抛错。"""
    calls = []

    async def fake(data_url: str) -> str:
        calls.append(data_url)
        if error is not None:
            raise error
        if isinstance(outputs, list):
            return outputs[len(calls) - 1]
        return outputs

    monkeypatch.setattr(llm, "recognize_image", fake)
    return calls


def _post_image(content: bytes = PNG_1PX, content_type: str = "image/png", field: str = "image"):
    return client.post(
        "/api/recognize",
        files={field: ("test.png", content, content_type)},
    )


# 1. 请求缺 image 字段 → 400 INVALID_FILE
def test_missing_image_field(monkeypatch):
    calls = _mock(monkeypatch, outputs="高风险")
    resp = client.post("/api/recognize", data={"other": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_FILE"
    assert calls == []  # 未发起模型调用


# 2. content_type 为 text/plain → 400 INVALID_FILE
def test_invalid_content_type(monkeypatch):
    calls = _mock(monkeypatch, outputs="高风险")
    resp = _post_image(content_type="text/plain")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_FILE"
    assert calls == []


# 3. 11MB 图片 → 400 INVALID_FILE
def test_oversize_image(monkeypatch):
    calls = _mock(monkeypatch, outputs="高风险")
    resp = _post_image(content=b"x" * (11 * 1024 * 1024))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_FILE"
    assert calls == []


# 4. mock 返回「高风险」→ 200 high,调用数 1
def test_success_first_try(monkeypatch):
    calls = _mock(monkeypatch, outputs="高风险")
    resp = _post_image()
    assert resp.status_code == 200
    assert resp.json() == {"level": "high"}
    assert len(calls) == 1
    assert calls[0].startswith("data:image/png;base64,")  # base64 data URL 拼装正确


# 5. mock 首次乱词、二次「中风险」→ 200 medium,调用数 2(S6 重试生效)
def test_retry_then_success(monkeypatch):
    calls = _mock(monkeypatch, outputs=["这个楼道很危险", "中风险"])
    resp = _post_image()
    assert resp.status_code == 200
    assert resp.json() == {"level": "medium"}
    assert len(calls) == 2


# 6. mock 两次乱词 → 502 MODEL_UNPARSABLE,调用数 2
def test_unparsable_after_retry(monkeypatch):
    calls = _mock(monkeypatch, outputs=["看不出来", "无法判断"])
    resp = _post_image()
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "MODEL_UNPARSABLE"
    assert len(calls) == 2


# 7. mock 抛 APITimeoutError → 504 MODEL_TIMEOUT,调用数 1(超时不重试)
def test_timeout_no_retry(monkeypatch):
    calls = _mock(
        monkeypatch,
        error=APITimeoutError(request=httpx.Request("POST", "http://test")),
    )
    resp = _post_image()
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "MODEL_TIMEOUT"
    assert len(calls) == 1


# 8. mock 抛一般 OpenAIError → 502 MODEL_UNPARSABLE(T7 兜底)
def test_openai_error_fallback(monkeypatch):
    calls = _mock(monkeypatch, error=OpenAIError("connection reset"))
    resp = _post_image()
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "MODEL_UNPARSABLE"
    assert len(calls) == 1


# 错误响应统一结构(PRD §6.1:所有失败 body 均为 {"error": {"code", "message"}})
@pytest.mark.parametrize(
    "kwargs",
    [
        {"content_type": "text/plain"},
        {"content": b"x" * (11 * 1024 * 1024)},
    ],
)
def test_error_body_shape(kwargs):
    resp = _post_image(**kwargs)
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message"}
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
