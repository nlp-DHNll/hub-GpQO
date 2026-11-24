"""推送：企业微信 / 飞书 / 钉钉群机器人 + SMTP 邮件。

设计约束
--------
1. **推送失败绝不影响出报告**。报告是主交付物，推送只是通知；``notify()`` 永远
   返回结果字典而不抛异常，失败原因写进 ``run_meta.json``，人能看到。
2. **不读命令行里的密钥**。URL、SMTP 密码只从环境变量或 ``config/.env`` 取，
   避免出现在 shell 历史与进程列表里。
3. **发送前不回显目标**。日志里只打印 ``host``，不打印含 token 的完整 URL。
4. 邮件正文是纯文本：HTML 邮件在各家邮箱客户端里渲染差异大，纯文本反而不会
   出现「价格表错位」这类事故。
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

import httpx

from .env import load_env  # 配置只从 env.py 读（白名单）
from . import netguard
from .render import fmt_amount  # 金额写法全项目只有一处实现

CHANNELS = ("webhook", "email")


def detect_channel(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "feishu" in host or "larksuite" in host:
        return "feishu"
    if "qyapi.weixin" in host or "wecom" in host:
        return "wecom"
    if "dingtalk" in host or "oapi.dingtalk" in host:
        return "dingtalk"
    return "generic"


def build_payload(url: str, title: str, text: str) -> dict[str, Any]:
    """按 webhook 厂商拼 payload。未知厂商用「企业微信 text」这种最常见形状。"""
    channel = detect_channel(url)
    if channel == "feishu":
        return {"msg_type": "text", "content": {"text": f"{title}\n{text}"}}
    if channel == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": title, "text": f"### {title}\n\n{text}"}}
    return {"msgtype": "text", "text": {"content": f"{title}\n{text}"}}


def build_message(context: dict[str, Any]) -> tuple[str, str]:
    """把报告上下文压成一条可读通知：标题 + 关键数字 + Top 5 + 报告路径。"""
    meta = context.get("meta") or {}
    stats = context.get("stats") or {}
    records = context.get("records") or []
    incremental = context.get("incremental") or {}

    prefix = "新增" if incremental else "本期"
    count = incremental.get("new", 0) if incremental else stats.get("total", 0)
    title = f"ESG 招标情报｜{prefix} {count} 条（{meta.get('generated_date', '')}）"

    lines = [
        f"窗口：近 {meta.get('days', '')} 天｜来源：{meta.get('provider', '')}",
        f"有效 {stats.get('total', 0)} 条｜有金额 {stats.get('amount_known', 0)} 条"
        f"｜中位数 {stats.get('amount_median', 'N/A')}｜合计 {stats.get('amount_sum', 'N/A')}",
    ]
    if incremental:
        lines.append(
            f"增量：本期新增 {incremental.get('new', 0)} 条，"
            f"往期已入库 {incremental.get('seen', 0)} 条"
        )
    stages = context.get("stages") or []
    if stages:
        lines.append("阶段：" + "｜".join(f"{item['label']} {item['count']}" for item in stages))

    top = records[:5]
    if top:
        lines.append("")
        lines.append(f"Top {len(top)}：")
        for index, record in enumerate(top, start=1):
            fields = record.get("fields") or {}
            raw = record.get("raw") or {}
            amount_text = fmt_amount(fields.get("amount_cny"))
            stage = (record.get("stage") or {}).get("label") or ""
            lines.append(
                f"{index}. {raw.get('title_clean') or raw.get('title')}"
                f"｜{(fields.get('buyer') or {}).get('value') or 'N/A'}"
                f"｜{amount_text}｜{stage}"
            )
    report = context.get("report_path")
    if report:
        lines.append("")
        lines.append(f"报告：{report}")
    return title, "\n".join(lines)


def send_webhook(
    url: str,
    title: str,
    text: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    payload = build_payload(url, title, text)
    host = urlparse(url).netloc
    # webhook URL 来自环境变量，同样可能是内网地址（或被改错）。
    # httpx 默认不跟随重定向，这里校验一次即可。
    try:
        netguard.assert_public_url(url)
    except netguard.BlockedAddress as exc:
        return {
            "ok": False,
            "channel": detect_channel(url),
            "target": host,
            "error": f"拒绝发送到非公网地址：{exc}",
        }
    try:
        if client is not None:
            response = client.post(url, json=payload)
        else:
            response = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:  # 网络异常种类多，统一降级
        return {"ok": False, "channel": detect_channel(url), "target": host, "error": type(exc).__name__}

    body = ""
    try:
        body = response.text[:200]
    except Exception:
        pass
    if not 200 <= response.status_code < 300:
        # 3xx 也算失败：httpx 默认不跟随重定向，302 说明 webhook 地址被换了或
        # 填的是短链，消息其实没送到群里。旧实现只判 >= 400，把 302 当成功。
        return {
            "ok": False,
            "channel": detect_channel(url),
            "target": host,
            "error": f"HTTP {response.status_code} {body}",
        }
    # 企业微信/钉钉出错时也返回 200，靠 errcode 判断
    if '"errcode"' in body and '"errcode":0' not in body.replace(" ", ""):
        return {"ok": False, "channel": detect_channel(url), "target": host, "error": body}
    return {"ok": True, "channel": detect_channel(url), "target": host, "error": ""}


def send_email(
    subject: str,
    text: str,
    *,
    env: dict[str, str] | None = None,
    smtp_factory: Any = None,
) -> dict[str, Any]:
    env = env or load_env()
    host = env.get("SMTP_HOST", "")
    port = int(env.get("SMTP_PORT", "465") or 465)
    user = env.get("SMTP_USER", "")
    password = env.get("SMTP_PASSWORD", "")
    sender = env.get("SMTP_FROM") or user
    recipients = [addr.strip() for addr in (env.get("SMTP_TO") or "").split(",") if addr.strip()]
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", host),
            ("SMTP_USER", user),
            ("SMTP_PASSWORD", password),
            ("SMTP_TO", recipients),
        )
        if not value
    ]
    if missing:
        return {"ok": False, "channel": "email", "target": host, "error": f"缺少 {', '.join(missing)}"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text)

    try:
        factory = smtp_factory or (
            smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        )
        with factory(host, port, timeout=20) as client:
            if port != 465:
                client.starttls(context=ssl.create_default_context())
            client.login(user, password)
            client.send_message(message)
    except Exception as exc:
        return {"ok": False, "channel": "email", "target": host, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "channel": "email", "target": host, "error": ""}


def notify(
    channel: str,
    context: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """发送通知。永不抛异常——失败信息返回给调用方落盘。"""
    env = env or load_env()
    title, text = build_message(context)
    if channel == "webhook":
        url = env.get("NOTIFY_WEBHOOK_URL") or env.get("WEBHOOK_URL") or ""
        if not url:
            return {"ok": False, "channel": "webhook", "target": "", "error": "缺少 NOTIFY_WEBHOOK_URL"}
        return send_webhook(url, title, text, client=client)
    if channel == "email":
        return send_email(title, text, env=env)
    return {"ok": False, "channel": channel, "target": "", "error": f"未知通道 {channel!r}"}
