"""iOS 27 毛玻璃设计规范（集中管理，便于调参）。

设计要点（与 ui-prototype.html 一致）：
- 背景：液态多彩渐变（青蓝 / 粉橙 / 紫罗兰柔光色块）；
- 玻璃材质：backdrop-filter blur + saturate + 半透明白 + 顶部镜面高光；
- 圆角：面板 22~30px、气泡 20px、输入栏 27px（连续曲率）；
- 状态色：成功 #34C759 / 警告 #FF9F0A / 失败 #FF3B30 / 主色 #0A84FF→#5AC8FA；
- 移动端：媒体查询收窄留白，输入栏避开底部安全区。
"""

IOS27_CSS = """
<style>
:root {
  --ink: #1c1c1e;
  --ink-2: #6e6e73;
  --accent: #0a84ff;
  --accent-2: #5ac8fa;
  --ok: #34c759;
  --warn: #ff9f0a;
  --fail: #ff3b30;
}

/* ── 隐藏 Streamlit 默认部件 ── */
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }

/* ── 液态多彩渐变背景（低端机自动降级为纯色） ── */
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(60vmax 60vmax at -15% -15%, rgba(90,200,250,.42), transparent 60%),
    radial-gradient(55vmax 55vmax at 115% 115%, rgba(255,107,107,.38), transparent 60%),
    radial-gradient(40vmax 40vmax at 85% 15%, rgba(161,140,209,.34), transparent 65%),
    radial-gradient(34vmax 34vmax at 15% 95%, rgba(251,194,235,.38), transparent 65%),
    #f2f2f7;
}

/* ── 主内容容器：桌面端呈手机卡片观感 ── */
[data-testid="stMain"] .block-container {
  max-width: 560px;
  padding-top: 1.2rem;
  padding-bottom: 6rem;
}

/* ── 顶部自定义导航（HTML） ── */
.app-header {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; margin-bottom: 6px; border-radius: 28px;
  background: rgba(255,255,255,.62);
  backdrop-filter: blur(26px) saturate(180%);
  -webkit-backdrop-filter: blur(26px) saturate(180%);
  border: 1px solid rgba(255,255,255,.8);
  box-shadow: 0 10px 40px rgba(31,38,135,.12), inset 0 1px 0 rgba(255,255,255,.9);
  position: relative; overflow: hidden;
}
.app-header::before {
  content: ""; position: absolute; inset: 1px; border-radius: inherit; pointer-events: none;
  background: linear-gradient(180deg, rgba(255,255,255,.5), rgba(255,255,255,.06) 40%, transparent 72%);
}
.app-header .avatar {
  width: 42px; height: 42px; border-radius: 13px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; color: #fff;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  box-shadow: 0 6px 16px rgba(10,132,255,.4), inset 0 1px 0 rgba(255,255,255,.6);
}
.app-header .header-txt { flex: 1; min-width: 0; }
.app-header h1 { font-size: 18px; font-weight: 700; margin: 0; color: var(--ink); }
.app-header p { font-size: 12px; color: var(--ink-2); margin: 1px 0 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.key-badge {
  display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0;
  padding: 6px 12px; border-radius: 999px; font-size: 11.5px; font-weight: 600;
  background: rgba(255,159,10,.14); color: #b26a00;
  border: 1px solid rgba(255,159,10,.4);
}
.key-badge .dot-b { width: 7px; height: 7px; border-radius: 50%; background: var(--warn); }
.key-badge.on { background: rgba(52,199,89,.14); color: #1e8e3e;
  border-color: rgba(52,199,89,.45); }
.key-badge.on .dot-b { background: var(--ok); box-shadow: 0 0 8px rgba(52,199,89,.8); }

/* ── 聊天气泡 ── */
.msg { display: flex; margin: 10px 0; animation: msgIn .3s cubic-bezier(.2,.9,.3,1.15); }
.msg.user { justify-content: flex-end; }
@keyframes msgIn { from { opacity: 0; transform: translateY(10px) scale(.97); } }
.msg .bubble {
  max-width: 86%; padding: 12px 15px; border-radius: 20px;
  font-size: 15px; line-height: 1.6; color: var(--ink);
}
.msg.assistant .bubble {
  background: rgba(255,255,255,.6);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,.75);
  border-top-left-radius: 7px;
  box-shadow: 0 4px 18px rgba(31,38,135,.08);
}
.msg.user .bubble {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff; border-top-right-radius: 7px;
  box-shadow: 0 6px 18px rgba(10,132,255,.35);
}
.msg.refuse .bubble {
  background: rgba(255,59,48,.12); border: 1px solid rgba(255,59,48,.35);
  color: #c62828; border-top-left-radius: 7px;
}
.msg.warn .bubble {
  background: rgba(255,159,10,.12); border: 1px solid rgba(255,159,10,.35);
  color: #b26a00; border-top-left-radius: 7px;
}

/* ── 执行轨迹卡（st.expander 重皮肤 + 逐步点亮动画） ── */
[data-testid="stExpander"] {
  background: rgba(255,255,255,.6);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,.75) !important;
  border-radius: 22px;
  box-shadow: 0 4px 18px rgba(31,38,135,.08);
}
[data-testid="stExpander"] details { border: none; }
[data-testid="stExpander"] summary { font-size: 13px; color: var(--ink-2); }
.trace { display: flex; flex-direction: column; gap: 2px; padding: 4px 2px; }
.step-row {
  display: flex; align-items: center; gap: 10px; padding: 7px 0;
  opacity: 0; animation: stepIn .45s ease forwards;
  animation-delay: calc(var(--i) * .18s);
}
@keyframes stepIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; } }
.step-row .dot { width: 9px; height: 9px; border-radius: 50%; background: #b0b0b8; flex-shrink: 0; }
.step-row.ok .dot { background: var(--ok); box-shadow: 0 0 8px rgba(52,199,89,.7); }
.step-row.warn .dot { background: var(--warn); }
.step-row.fail .dot { background: var(--fail); box-shadow: 0 0 8px rgba(255,59,48,.6); }
.step-row .step-name { flex: 1; font-size: 13.5px; font-weight: 500; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.step-row .step-det { font-size: 11px; color: var(--ink-2); max-width: 42%;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.step-row .chip { flex-shrink: 0; font-size: 11px; font-weight: 600; padding: 2.5px 9px;
  border-radius: 999px; background: rgba(0,0,0,.06); color: var(--ink-2); }
.step-row.ok .chip { background: rgba(52,199,89,.14); color: #1e8e3e; }
.step-row.warn .chip { background: rgba(255,159,10,.14); color: #b26a00; }
.step-row.fail .chip { background: rgba(255,59,48,.14); color: #c62828; }

/* ── 底部输入区：与主区同宽、透明底 ── */
[data-testid="stBottom"] {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
[data-testid="stBottomBlockContainer"] {
  max-width: 560px;
  margin-left: auto !important;
  margin-right: auto !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
}

/* ── 输入栏：玻璃胶囊（外层描边 + 内部全透明 + 圆形渐变发送钮） ── */
[data-testid="stChatInput"] {
  background: rgba(255,255,255,.62) !important;
  backdrop-filter: blur(26px) saturate(180%);
  -webkit-backdrop-filter: blur(26px) saturate(180%);
  border: 1px solid rgba(255,255,255,.8) !important;
  border-radius: 27px !important;
  box-shadow: 0 10px 40px rgba(31,38,135,.14), inset 0 1px 0 rgba(255,255,255,.9) !important;
  padding: 6px 8px 6px 18px !important;
  transition: border-color .25s ease, box-shadow .25s ease;
}
[data-testid="stChatInput"]:focus-within {
  border-color: rgba(10,132,255,.55) !important;
  box-shadow: 0 10px 40px rgba(31,38,135,.16),
              0 0 0 4px rgba(10,132,255,.12),
              inset 0 1px 0 rgba(255,255,255,.9) !important;
}
/* 胶囊内部全透明：消除「椭圆内套矩形」的观感 */
[data-testid="stChatInput"] div {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
[data-testid="stChatInput"] textarea {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: var(--ink) !important;
  caret-color: var(--accent);
  font-size: 15px !important;
  line-height: 1.5 !important;
  padding: 9px 6px 9px 0 !important;
}
[data-testid="stChatInput"] textarea::placeholder {
  color: rgba(60,60,67,.38);
}
[data-testid="stChatInputSubmitButton"] {
  width: 40px !important;
  height: 40px !important;
  min-width: 40px !important;
  border: none !important;
  border-radius: 50% !important;
  background: linear-gradient(135deg, var(--accent), var(--accent-2)) !important;
  color: #fff !important;
  box-shadow: 0 6px 16px rgba(10,132,255,.4) !important;
  transition: transform .15s ease, box-shadow .2s ease, opacity .2s ease !important;
}
[data-testid="stChatInputSubmitButton"]:hover:not(:disabled) {
  background: linear-gradient(135deg, #2d9bff, #6fd0ff) !important;
  transform: scale(1.06);
  box-shadow: 0 8px 20px rgba(10,132,255,.5) !important;
}
[data-testid="stChatInputSubmitButton"]:disabled {
  background: rgba(60,60,67,.1) !important;
  box-shadow: none !important;
  opacity: .6;
}
[data-testid="stChatInputSubmitButton"] svg {
  fill: #fff !important;
  color: #fff !important;
}

/* ── 设置按钮：全宽玻璃胶囊（1.60 按钮 DOM: button[data-testid^=stBaseButton]） ── */
button[data-testid^="stBaseButton"] {
  width: 100%;
  border-radius: 22px;
  background: rgba(255,255,255,.62);
  backdrop-filter: blur(26px) saturate(180%);
  -webkit-backdrop-filter: blur(26px) saturate(180%);
  border: 1px solid rgba(255,255,255,.8);
  color: var(--ink);
  font-weight: 600;
  font-size: 14px;
  padding: 10px 16px;
  box-shadow: 0 6px 20px rgba(31,38,135,.1), inset 0 1px 0 rgba(255,255,255,.9);
  transition: border-color .2s ease, color .2s ease, background .2s ease;
}
button[data-testid^="stBaseButton"]:hover {
  border-color: rgba(10,132,255,.5);
  color: var(--accent);
  background: rgba(255,255,255,.78);
}
button[data-testid="stBaseButton-primary"] {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  border: none;
  box-shadow: 0 6px 16px rgba(10,132,255,.4);
}
button[data-testid="stBaseButton-primary"]:hover {
  background: linear-gradient(135deg, #2d9bff, #6fd0ff);
  color: #fff;
}

/* ── 弹窗（st.dialog）：玻璃卡片 ──
   stDialog = 外层 overlay（含遮罩，不可染背景色）；
   > div = 卡片容器，玻璃材质画在这里；> div > div = 内层，全透明。 */
[data-testid="stDialog"] > div {
  background: rgba(250,250,252,.88) !important;
  border-radius: 26px !important;
  border: 1px solid rgba(255,255,255,.9);
  box-shadow: 0 24px 70px rgba(31,38,135,.28), inset 0 1px 0 rgba(255,255,255,.95);
  backdrop-filter: blur(30px) saturate(180%);
  -webkit-backdrop-filter: blur(30px) saturate(180%);
  overflow: hidden;
}
[data-testid="stDialog"] > div > div {
  background: transparent !important;
}
[data-testid="stDialog"] input {
  background: rgba(255,255,255,.85) !important;
  border: 1px solid rgba(0,0,0,.1) !important;
  border-radius: 14px !important;
  padding: 10px 14px !important;
}
[data-testid="stDialog"] input:focus {
  border-color: rgba(10,132,255,.55) !important;
  box-shadow: 0 0 0 4px rgba(10,132,255,.12) !important;
}

/* ── 移动端适配（375px 起） ── */
@media (max-width: 640px) {
  [data-testid="stMain"] .block-container {
    padding: 0.8rem 0.8rem 5.5rem;
  }
  .msg .bubble { max-width: 92%; font-size: 15px; }
  .app-header h1 { font-size: 17px; }
  [data-testid="stChatInput"] { padding: 5px 6px 5px 14px !important; }
  [data-testid="stBottom"] { padding-bottom: env(safe-area-inset-bottom); }
}
</style>
"""
