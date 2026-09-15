"""Streamlit Web UI

启动方式:
    streamlit run web/app.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import streamlit as st

# 把项目根目录加入 path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.qa_pipeline import QAPipeline  # noqa: E402

logging.basicConfig(level=logging.WARNING)

st.set_page_config(
    page_title="电商智能问答",
    page_icon="🛒",
    layout="wide",
)

# ---------- 流水线缓存 ----------
@st.cache_resource
def get_pipeline() -> QAPipeline:
    return QAPipeline()


def init_state():
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "您好!我是电商智能客服小淘~请问有什么可以帮您?😊"}
        ]
    if "last_trace" not in st.session_state:
        st.session_state.last_trace = None
    if "session_state" not in st.session_state:
        try:
            pipe = get_pipeline()
            st.session_state.session_state = pipe.dm.new_session()
        except Exception:
            st.session_state.session_state = None


def render_sidebar(pipe: QAPipeline):
    with st.sidebar:
        st.title("🛒 电商智能问答")
        st.caption("RAG + BM25 + Neo4j + DeepSeek")
        st.divider()
        st.subheader("📡 依赖状态")
        try:
            status = pipe.self_check()
            for k, v in status.items():
                if "✅" in v:
                    st.success(f"**{k}**: {v.replace('✅ ', '')}", icon="✅")
                elif "⚠️" in v:
                    st.warning(f"**{k}**: {v.replace('⚠️ ', '')}", icon="⚠️")
                else:
                    st.error(f"**{k}**: {v.replace('❌ ', '')}", icon="❌")
        except Exception as e:  # noqa: BLE001
            st.error(f"自检失败: {e}")
        st.divider()
        st.subheader("🔍 检索证据")
        if st.session_state.get("last_sources"):
            for s in st.session_state.last_sources[:5]:
                st.caption(f"**{s['head']}** {s['relation']} *{s['tail']}*")
        else:
            st.caption("尚无检索记录")
        st.divider()
        if st.button("🔄 重置对话", use_container_width=True):
            st.session_state.messages = [
                {"role": "assistant", "content": "已重置,我是小淘,请问有什么可以帮您?"}
            ]
            st.session_state.last_trace = None
            st.session_state.last_sources = None
            try:
                st.session_state.session_state = pipe.dm.new_session()
            except Exception:
                st.session_state.session_state = None
            st.rerun()
        st.caption("💡 提示:试试问「iPhone 15 电池容量多大？」")


def main():
    st.title("🛒 电商智能问答系统")
    init_state()

    # 尝试加载 pipeline
    try:
        pipe = get_pipeline()
    except Exception as e:  # noqa: BLE001
        st.error(f"❌ 流水线初始化失败: {e}")
        st.info(
            "**修复步骤:**\n"
            "1. 启动 Neo4j: `docker run -d -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j`\n"
            "2. 灌库: `python scripts/init_neo4j.py`\n"
            "3. 设置 `DEEPSEEK_API_KEY` 环境变量"
        )
        return

    render_sidebar(pipe)

    # ---------- 聊天窗口 ----------
    for msg in st.session_state.messages:
        avatar = "🤖" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # 用户输入
    if prompt := st.chat_input("请输入您的问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar="🤖"):
            placeholder = st.empty()
            placeholder.markdown("🤔 思考中...")
            try:
                result = pipe.ask(prompt, session_state=st.session_state.session_state)
            except Exception as e:  # noqa: BLE001
                placeholder.error(f"❌ {e}")
                return
            placeholder.markdown(result.answer)
            st.session_state.last_sources = result.sources
            st.session_state.last_trace = result.trace
            # 元信息
            with st.expander("📊 调试信息", expanded=False):
                cols = st.columns(4)
                cols[0].metric("意图", result.intent)
                cols[1].metric("置信度", f"{result.confidence:.2f}")
                cols[2].metric("检索条数", len(result.sources))
                cols[3].metric("耗时", f"{result.latency_ms}ms")
                if result.trace:
                    st.caption("trace: " + " | ".join(result.trace))
                if result.follow_up_question:
                    st.info(f"💡 追问引导: {result.follow_up_question}")
        st.session_state.messages.append({"role": "assistant", "content": result.answer})


if __name__ == "__main__":
    main()