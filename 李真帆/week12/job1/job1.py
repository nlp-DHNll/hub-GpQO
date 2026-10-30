"""
楼道风险监控识别 —— 前端模块（Streamlit，兼容手机端）+ mainapp 启动器

模块划分（本作业由两个模块组成，mainapp 一条命令同时拉起）：
    1. backend.py（后端）：FastAPI + LangChain 调用 DeepSeek(deepseek-flash 多模态)，
       接收图片并流式返回楼道堆物 / 火灾隐患的分析结果；
    2. 本文件（前端）：点击拍照 / 上传一张楼道照片 -> 请求后端 /analyze
       -> 用 st.write_stream 流式展示，并把风险等级做成彩色徽标；
    3. mainapp：python job1.py 直接启动上面两个进程（后端 8000 / 前端 8501）。

运行（先在 backend.py 顶部填好 DEEPSEEK_API_KEY）：
    python job1.py
    电脑访问 http://127.0.0.1:8501 ；手机访问 http://<电脑IP>:8501（与电脑同一局域网）
    手机端点击上传框即可直接调用相机拍照，每次只上传 / 分析一张图片。

为什么 FastAPI 不写在 job1.py 里：新版 `streamlit run` 会扫描入口脚本，
一旦发现脚本里创建了 FastAPI/Starlette 实例（变量名任意），就把它当 ASGI 服务入口启动，
前端界面反而不会被渲染，所以后端必须独立成 backend.py。

依赖：langchain langchain-openai fastapi uvicorn python-multipart requests streamlit
"""

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import requests
import streamlit as st

# 后端配置统一在 backend.py，避免两个模块各写一份地址
from backend import BACKEND_URL, MAX_IMAGE_MB

APP_NAME = "楼道风险监控识别"
THIS_FILE = str(Path(__file__).resolve())
BACKEND_FILE = str(Path(THIS_FILE).with_name("backend.py"))
FRONTEND_PORT = 8501

# 风险等级 -> 前端徽标颜色 / 图标
RISK_COLOR = {"高风险": "red", "中等风险": "orange", "低风险": "yellow", "无隐患": "green", "非楼道": "gray"}
RISK_ICON = {"高风险": ":material/local_fire_department:", "中等风险": ":material/warning:",
             "低风险": ":material/report:", "无隐患": ":material/verified:", "非楼道": ":material/image_not_supported:"}
RISK_LEVELS = ["高风险", "中等风险", "低风险", "无隐患", "非楼道"]
# 模型可能写出的同义词，归一化到标准等级（按顺序匹配，先判“非楼道”类信号）
RISK_ALIAS = {"无关": "非楼道", "非楼梯": "非楼道", "非走廊": "非楼道",
              "中风险": "中等风险", "中等": "中等风险", "无风险": "无隐患", "干净": "无隐患"}


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def local_ip() -> str:
    """取本机局域网 IP，方便手机直接输入地址访问。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def backend_health() -> dict:
    """探一次后端；没起来就返回空字典。"""
    try:
        return requests.get(f"{BACKEND_URL}/health", timeout=2).json()
    except requests.RequestException:
        return {}


def parse_risk(text: str) -> str:
    """从模型回复里取风险等级：优先看“风险等级”那一行，再按高->低风险顺序兜底匹配。"""
    line = next((row for row in text.splitlines() if "风险等级" in row), text)
    for level in RISK_LEVELS:
        if level in line:
            return level
    for alias, level in RISK_ALIAS.items():
        if alias in line:
            return level
    return "非楼道"


def stream_tokens(filename: str, data: bytes, mime: str) -> Iterator[str]:
    """读后端的 NDJSON 流，把文本块原样吐给 st.write_stream。"""
    with requests.post(f"{BACKEND_URL}/analyze", files={"file": (filename, data, mime)},
                       stream=True, timeout=300) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"后端返回 {resp.status_code}：{resp.text[:200]}")
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            frame = json.loads(line)
            if "text" in frame:
                yield frame["text"]
            elif "error" in frame:
                raise RuntimeError(frame["error"])


# ═══════════════════════════════════════════════════════════════════════════════
# 前端模块：拍照 / 上传 -> 流式分析结果
# ═══════════════════════════════════════════════════════════════════════════════

def run_frontend() -> None:
    """前端模块入口（layout=centered 天然适配手机端）。"""
    st.set_page_config(page_title=APP_NAME, page_icon=":material/camera_indoor:", layout="centered")

    st.title(APP_NAME)
    st.caption("拍一张楼道照片，自动识别堆物与火灾隐患")

    # 每次 rerun 都探一次后端，后端稍后启动时刷新页面即可恢复
    info = backend_health()
    if not info:
        st.badge("后端未就绪，请先运行 python job1.py", color="red", icon=":material/link_off:")
        return
    st.badge(f"后端已连接 · {info.get('model', '')}", color="green", icon=":material/link:")
    key_ready = bool(info.get("key_ready"))
    if not key_ready:
        st.warning("请先在 backend.py 顶部填写 DEEPSEEK_API_KEY")

    uploaded = st.file_uploader("点击拍照 / 上传图片", type=["jpg", "jpeg", "png", "webp", "bmp"], key="photo")
    if uploaded is None:
        st.info(f"手机端点击后可直接调用相机拍照；每次仅分析一张图片（jpg / png / webp / bmp，≤{MAX_IMAGE_MB}MB）")
        return

    data = uploaded.read()
    st.image(data, caption=uploaded.name)

    # 换了一张图就清掉上一条结论，避免新旧结果混在一起
    if st.session_state.get("last_name") != uploaded.name:
        st.session_state.update(last_name=uploaded.name, answer="", streamed=False)

    if st.button("开始分析", type="primary", icon=":material/manage_search:", disabled=not key_ready):
        st.session_state["answer"] = ""
        try:
            st.session_state["answer"] = st.write_stream(stream_tokens(uploaded.name, data, uploaded.type))
            st.session_state["streamed"] = True
        except Exception as exc:
            st.error(f"分析失败：{exc}")

    answer = st.session_state.get("answer", "")
    if answer:
        risk = parse_risk(answer)
        st.badge(f"识别结果：{risk}", color=RISK_COLOR[risk], icon=RISK_ICON[risk])
        # 本轮之后的 rerun 不会再输出流式内容，这里补一次正文，保证画面稳定
        if not st.session_state.pop("streamed", False):
            st.markdown(answer)

    st.divider()
    st.caption(f"手机访问地址：http://{local_ip()}:{FRONTEND_PORT}")


# ═══════════════════════════════════════════════════════════════════════════════
# mainapp：一条命令同时启动后端与前端两个模块
# ═══════════════════════════════════════════════════════════════════════════════

def mainapp() -> None:
    """拉起两个子进程：后端 FastAPI（8000）+ 前端 Streamlit（8501）。"""
    backend = subprocess.Popen([sys.executable, BACKEND_FILE])

    # streamlit run 本文件时用 APP_MODE 告诉子进程“这一次要渲染前端界面”
    frontend = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", THIS_FILE,
         "--server.port", str(FRONTEND_PORT),
         "--server.address", "0.0.0.0",
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        env={**os.environ, "APP_MODE": "frontend"},
    )

    print("=" * 70)
    print(f"{APP_NAME} 已启动")
    print(f"    电脑访问：http://127.0.0.1:{FRONTEND_PORT}")
    print(f"    手机访问：http://{local_ip()}:{FRONTEND_PORT}（与电脑同一局域网）")
    print("    按 Ctrl+C 退出")
    print("=" * 70)

    try:
        frontend.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (frontend, backend):
            proc.terminate()


if __name__ == "__main__":
    # streamlit run 也会把脚本当 __main__ 执行，所以用 APP_MODE 区分“渲染界面”还是“当入口启动”
    if os.environ.get("APP_MODE") == "frontend" or st.runtime.exists():
        run_frontend()
    else:
        mainapp()
