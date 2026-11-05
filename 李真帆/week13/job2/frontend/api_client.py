"""HTTP 客户端：对接 FastAPI 后端。

前端只发 HTTP 请求，不在本进程内实例化任何 FastAPI 对象
（Streamlit 会自动接管脚本内的 FastAPI 实例，导致前端不渲染）。
"""

import os

import requests

# 后端地址可用环境变量覆盖（默认本机 8000）
BACKEND_URL = os.getenv("SQL_AGENT_BACKEND", "http://127.0.0.1:8000")

# 工作流最多 3 轮、每轮多次 LLM 调用，超时给足
TIMEOUT = 300


class ApiError(Exception):
    """后端返回的业务错误（Key 无效 / 限流 / 内部错误 / 连不上等）。"""


def health() -> bool:
    """探测后端是否在线。"""
    try:
        return requests.get(f"{BACKEND_URL}/health", timeout=3).ok
    except requests.RequestException:
        return False


def chat(question: str, api_key: str, session_id: str = "") -> dict:
    """发送一次问答请求。

    :return: 成功时返回响应 JSON（answer / trace / sql / tables / rounds）
    :raises ApiError: 后端不可达或返回错误时抛出，消息可直接展示给用户
    """
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/chat",
            json={"question": question, "api_key": api_key, "session_id": session_id},
            timeout=TIMEOUT,
        )
    except requests.exceptions.ConnectionError as exc:
        raise ApiError("无法连接后端服务：请先在 backend 目录运行 python run.py") from exc
    except requests.exceptions.Timeout as exc:
        raise ApiError("请求超时：工作流执行时间过长，请稍后重试") from exc
    except requests.RequestException as exc:
        raise ApiError(f"网络异常：{exc}") from exc

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "服务异常")
        except ValueError:
            detail = f"后端返回 {resp.status_code}"
        raise ApiError(str(detail))

    return resp.json()
