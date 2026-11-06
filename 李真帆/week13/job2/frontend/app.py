"""SQL 数据智能体 · Streamlit 前端（iOS 27 毛玻璃风格）。

- 用户点击顶部设置按钮，在弹出的对话框中自定义 DeepSeek API Key（仅存 session_state，刷新即失）；
- 对话框提问，由 FastAPI 后端驱动 job1 的 LangGraph 工作流回答；
- 不相关问题由工作流返回固定话术，前端渲染为红色拒绝气泡；
- 移动端自适应（媒体查询 + 底部安全区）。

用法：
    streamlit run app.py
（需先在 backend 目录运行 python run.py 启动后端）
"""

import html

import streamlit as st

from api_client import ApiError, chat as backend_chat, health as backend_health
from styles import IOS27_CSS

# ═══════════════════════════════════════════════════════════════════════════════
# 页面配置
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="SQL 数据智能体",
    page_icon=":material/database:",
    layout="centered",
)

st.markdown(IOS27_CSS, unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "api_key" not in st.session_state:
    st.session_state.api_key = ""

# ═══════════════════════════════════════════════════════════════════════════════
# 渲染工具
# ═══════════════════════════════════════════════════════════════════════════════

_AVATAR_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="color:#fff">'
    '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'
    '</svg>'
)


def _header_html(has_key: bool) -> str:
    """顶部玻璃导航栏：标题 + Key 状态徽标。"""
    badge = (
        '<span class="key-badge on"><span class="dot-b"></span>Key 已配置</span>'
        if has_key
        else '<span class="key-badge"><span class="dot-b"></span>未配置 Key</span>'
    )
    return (
        '<div class="app-header">'
        f'<div class="avatar">{_AVATAR_SVG}</div>'
        '<div class="header-txt"><h1>SQL 数据智能体</h1>'
        '<p>Chinook 音乐数据库 · LangGraph 工作流</p></div>'
        f'{badge}'
        '</div>'
    )


def _bubble(kind: str, content: str) -> str:
    """一条聊天气泡（kind: user / assistant / refuse / warn）。"""
    text = html.escape(content).replace("\n", "<br>")
    return f'<div class="msg {kind}"><div class="bubble">{text}</div></div>'


def _trace_html(trace: list[dict]) -> str:
    """执行轨迹卡：每步 = 状态圆点 + 节点名 + 摘要 + 状态 chip，逐步点亮。"""
    rows = []
    for i, step in enumerate(trace):
        status = str(step.get("status") or "")
        agent = str(step.get("agent") or "")
        name = str(step.get("step") or agent)
        detail = str(step.get("detail") or "")
        if status == "ok":
            chip = "通过"
        elif status == "warn":
            chip = "回退"
        elif status == "fail":
            chip = "拒绝" if agent == "Router" else "失败"
        else:
            chip = "—"
        rows.append(
            f'<div class="step-row {status}" style="--i:{i}">'
            f'<span class="dot"></span>'
            f'<span class="step-name">{html.escape(name)}</span>'
            f'<span class="step-det">{html.escape(detail)}</span>'
            f'<span class="chip">{chip}</span></div>'
        )
    return '<div class="trace">' + "".join(rows) + "</div>"


def _render_messages() -> None:
    """按顺序渲染历史消息。"""
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(_bubble("user", msg["content"]), unsafe_allow_html=True)
            continue
        if msg.get("refused"):
            kind = "refuse"
        elif msg.get("kind") == "warn":
            kind = "warn"
        else:
            kind = "assistant"
        st.markdown(_bubble(kind, msg["content"]), unsafe_allow_html=True)
        trace = msg.get("trace") or []
        if trace:
            with st.expander("执行轨迹 · LangGraph 工作流", expanded=bool(msg.get("refused"))):
                st.markdown(_trace_html(trace), unsafe_allow_html=True)
                if msg.get("sql"):
                    st.caption("最终 SQL")
                    st.code(msg["sql"], language="sql")


# ═══════════════════════════════════════════════════════════════════════════════
# API Key 弹窗：点击设置按钮弹出（手机端友好）
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=15)
def _backend_online() -> bool:
    """后端健康探测（15 秒缓存，避免每次重跑都发请求）。"""
    return backend_health()


@st.dialog("设置 DeepSeek API Key", width="small")
def _key_dialog() -> None:
    """API Key 设置弹窗：保存/清除后 rerun 自动关闭。"""
    st.caption("Key 仅保存在本次会话内存中，刷新页面后需重新填写。")
    key_input = st.text_input(
        "API Key",
        type="password",
        value=st.session_state.api_key,
        placeholder="sk-xxxxxxxxxxxxxxxx",
        help="DeepSeek 开放平台的 API Key，仅本次请求使用",
        label_visibility="collapsed",
    )
    col_save, col_clear = st.columns([1, 1])
    if col_save.button("保存", type="primary", use_container_width=True):
        if key_input.strip():
            st.session_state.api_key = key_input.strip()
            st.toast("API Key 已保存（仅本次会话）")
            st.rerun()
        else:
            st.warning("请先填写 API Key")
    if col_clear.button("清除", use_container_width=True):
        st.session_state.api_key = ""
        st.rerun()
    st.divider()
    if _backend_online():
        st.caption("后端服务：在线 (127.0.0.1:8000)")
    else:
        st.caption("后端服务：离线 —— 请在 backend 目录运行 python run.py")

# ═══════════════════════════════════════════════════════════════════════════════
# 主区：导航栏 + 聊天流 + 输入框
# ═══════════════════════════════════════════════════════════════════════════════

has_key = bool(st.session_state.api_key)
st.markdown(_header_html(has_key), unsafe_allow_html=True)

settings_label = "API Key 已配置 · 点击修改" if has_key else "设置 DeepSeek API Key（必填）"
if st.button(
    settings_label,
    icon=":material/tune:",
    use_container_width=True,
    key="open_key_dialog",
):
    _key_dialog()

if not st.session_state.messages:
    st.markdown(
        _bubble(
            "assistant",
            "你好，我是 SQL 数据智能体，可以回答 Chinook 音乐数据库的统计问题。\n"
            "例如：「每种音乐类型下有多少首曲目？」「哪个国家的订单总金额最高？」\n"
            "与音乐数据库无关的问题我会拒绝回答。",
        ),
        unsafe_allow_html=True,
    )

_render_messages()

question = st.chat_input("输入要查询的问题，例如：每个国家的订单总额排名")

if question:
    if not st.session_state.api_key:
        # 未配置 Key：直接以警告气泡提示，不发请求
        st.session_state.messages.append({
            "role": "assistant",
            "content": "请先点击上方设置按钮，填写 DeepSeek API Key，再向我提问。",
            "refused": False,
            "trace": [],
            "sql": "",
            "kind": "warn",
        })
        st.rerun()

    st.session_state.messages.append({"role": "user", "content": question})

    with st.spinner("SQL Agent 工作流执行中，请稍候……"):
        try:
            data = backend_chat(question, st.session_state.api_key)
        except ApiError as exc:
            st.session_state.messages.append({
                "role": "assistant",
                "content": str(exc),
                "refused": False,
                "trace": [],
                "sql": "",
                "kind": "warn",
            })
            st.rerun()

    st.session_state.messages.append({
        "role": "assistant",
        "content": data.get("answer", ""),
        "refused": bool(data.get("rejected")),
        "trace": data.get("trace") or [],
        "sql": data.get("sql") or "",
    })
    st.rerun()
