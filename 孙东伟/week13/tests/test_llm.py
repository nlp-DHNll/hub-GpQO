"""模型层测试：LangGraph 节点直调模型，不依赖 API key，也不发起真实调用。"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from sql_agent.agents import AGENTS, table_selector_agent
from sql_agent.config import settings
from sql_agent.llm import StructuredAgent, _parse_message, _resolve_tool_choice
from sql_agent.models import FinalAnswer, SQLDraft, TableSelection


def test_agents_import_without_api_key(monkeypatch) -> None:
    """导入期只建提示词，不应要求 API key。"""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert {agent.name for agent in AGENTS} == {
        "TableSelectAgent",
        "SQLGeneratorAgent",
        "SQLRewriteAgent",
        "ResultSummaryAgent",
    }
    assert table_selector_agent.output_type is TableSelection
    assert [agent.output_type for agent in AGENTS] == [
        TableSelection,
        SQLDraft,
        SQLDraft,
        FinalAnswer,
    ]


def test_model_configuration_follows_settings(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = StructuredAgent(
        name="ProbeAgent",
        instructions="只输出结构化结果。",
        output_type=FinalAnswer,
        model=settings.primary_model,
        temperature=0.2,
    )

    model = agent.create_model()

    assert model.model_name == settings.primary_model
    assert model.temperature == 0.2
    assert f"{model.openai_api_base}".rstrip("/") == settings.base_url.rstrip("/")
    assert model.max_retries == settings.llm_max_retries


def test_build_messages_keeps_system_and_user_parts() -> None:
    agent = StructuredAgent(
        name="ProbeAgent",
        instructions="你是测试助手。",
        output_type=FinalAnswer,
        model="probe-model",
    )

    messages = agent.build_messages("<question>你好</question>")

    # system 提示保留原始指令，并追加"必须调用工具"的输出约定。
    assert messages[0].content.startswith("你是测试助手。")
    assert agent.tool_name in messages[0].content
    assert messages[1].content == "<question>你好</question>"
    assert [message.type for message in messages] == ["system", "human"]


def test_build_messages_appends_parse_hint() -> None:
    agent = StructuredAgent(
        name="ProbeAgent",
        instructions="你是测试助手。",
        output_type=FinalAnswer,
        model="probe-model",
    )

    messages = agent.build_messages("问题", error=ValueError("bad json"))

    assert "无法解析" in messages[-1].content
    assert "bad json" in messages[-1].content


def test_bound_model_binds_tools_with_auto(monkeypatch) -> None:
    """思考模式模型只接受 tool_choice=auto，不能被强制指定具体函数。"""

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = StructuredAgent(
        name="ProbeAgent",
        instructions="你是测试助手。",
        output_type=FinalAnswer,
        model="probe-model",
    )

    binding = agent.bound_model

    assert binding.kwargs["tool_choice"] == "auto"
    tool = binding.kwargs["tools"][0]
    assert tool["function"]["name"] == "FinalAnswer"
    assert "answer" in tool["function"]["parameters"]["properties"]


def test_resolve_tool_choice_maps_config_values() -> None:
    assert _resolve_tool_choice(None, "SQLDraft") == "auto"
    assert _resolve_tool_choice("auto", "SQLDraft") == "auto"
    assert _resolve_tool_choice("SQLDraft", "SQLDraft") == {
        "type": "function",
        "function": {"name": "SQLDraft"},
    }
    # 未知取值（含 required）回退为 auto，避免触发 400。
    assert _resolve_tool_choice("typo", "SQLDraft") == "auto"
    assert _resolve_tool_choice("required", "SQLDraft") == "auto"


def test_parse_message_prefers_tool_call_arguments() -> None:
    message = AIMessage(
        content="",
        tool_calls=[
            {"name": "FinalAnswer", "args": {"answer": "共 347 张专辑"}, "id": "1"}
        ],
    )

    parsed, error = _parse_message(message, FinalAnswer, "FinalAnswer")

    assert error is None
    assert parsed is not None and parsed.answer == "共 347 张专辑"


def test_parse_message_falls_back_to_content_json() -> None:
    message = AIMessage(content='```json\n{"answer": "42"}\n```')

    parsed, error = _parse_message(message, FinalAnswer, "FinalAnswer")

    assert error is None
    assert parsed is not None and parsed.answer == "42"


def test_parse_message_reports_error_when_nothing_parses() -> None:
    parsed, error = _parse_message(AIMessage(content="我不知道"), FinalAnswer, "FinalAnswer")

    assert parsed is None
    assert isinstance(error, Exception)


def test_ainvoke_retries_once_on_parse_error(monkeypatch) -> None:
    agent = StructuredAgent(
        name="ProbeAgent",
        instructions="你是测试助手。",
        output_type=FinalAnswer,
        model="probe-model",
    )
    payloads: list = []

    class FakeBoundModel:
        async def ainvoke(self, messages):
            payloads.append(messages[-1].content)
            if len(payloads) == 1:
                return AIMessage(content="无法输出")
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "FinalAnswer", "args": {"answer": "好的"}, "id": "1"}
                ],
            )

    monkeypatch.setattr(
        StructuredAgent, "bound_model", property(lambda self: FakeBoundModel())
    )

    result = asyncio.run(agent.ainvoke("问题"))

    assert result.answer == "好的"
    assert len(payloads) == 2
    assert "无法解析" in payloads[1]


def test_ainvoke_raises_when_parse_keeps_failing(monkeypatch) -> None:
    agent = StructuredAgent(
        name="ProbeAgent",
        instructions="你是测试助手。",
        output_type=FinalAnswer,
        model="probe-model",
    )

    class FakeBoundModel:
        async def ainvoke(self, messages):
            return AIMessage(content="始终不是 JSON")

    monkeypatch.setattr(
        StructuredAgent, "bound_model", property(lambda self: FakeBoundModel())
    )

    with pytest.raises(TypeError, match="FinalAnswer"):
        asyncio.run(agent.ainvoke("问题"))
