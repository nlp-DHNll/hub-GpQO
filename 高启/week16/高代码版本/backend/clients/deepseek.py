"""通过 OpenAI SDK 调用 DeepSeek，并加载各步骤的独立提示词。"""

import json

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion

from ..config import PROMPT_DIR
from ..enums import StepName
from ..errors import RunFailure
from ..log.run_logger import RunLogger

INITIAL_MAX_TOKENS = 8192
RETRY_MAX_TOKENS = 16384
RETRY_INSTRUCTION = (
    "上一份输出未完整结束。请缩短铺垫和重复内容，保留要求的章节、引用和输出格式，"
    "一次返回完整结果。"
)


class DeepSeekClient:
    """封装模型请求、输出格式和可安全展示的错误。"""

    def __init__(self, sdk: OpenAI, model: str) -> None:
        self._sdk = sdk
        self._model = model

    def complete_text(self, step: StepName, data: dict[str, object], *, logger: RunLogger) -> str:
        return self._complete(step, data, logger=logger, json_mode=False)

    def complete_json(
        self, step: StepName, data: dict[str, object], *, logger: RunLogger,
    ) -> dict[str, object]:
        content = self._complete(step, data, logger=logger, json_mode=True)
        try:
            value = json.loads(content)
        except json.JSONDecodeError as error:
            raise RunFailure("DeepSeek 返回的 JSON 无法解析") from error
        if not isinstance(value, dict):
            raise RunFailure("DeepSeek 返回的 JSON 应为对象")
        return value

    def _complete(
        self, step: StepName, data: dict[str, object], *, logger: RunLogger, json_mode: bool,
    ) -> str:
        try:
            prompt = (PROMPT_DIR / f"{step.value}.md").read_text(encoding="utf-8")
        except OSError as error:
            raise RunFailure(f"无法读取步骤提示词：{step.value}.md") from error

        payload = json.dumps(data, ensure_ascii=False)
        for max_tokens in (INITIAL_MAX_TOKENS, RETRY_MAX_TOKENS):
            retry = max_tokens == RETRY_MAX_TOKENS
            response = self._request(
                f"{prompt}\n\n{RETRY_INSTRUCTION}" if retry else prompt,
                payload,
                json_mode=json_mode,
                max_tokens=max_tokens,
                disable_thinking=not json_mode or retry,
            )
            if not response.choices:
                raise RunFailure("DeepSeek 未返回模型结果")
            choice = response.choices[0]
            if choice.finish_reason == "length":
                details: dict[str, object] = {"max_tokens": max_tokens}
                if not retry:
                    details["next_max_tokens"] = RETRY_MAX_TOKENS
                if response.usage is not None:
                    details["prompt_tokens"] = response.usage.prompt_tokens
                    details["completion_tokens"] = response.usage.completion_tokens
                    usage_details = response.usage.completion_tokens_details
                    if usage_details is not None and usage_details.reasoning_tokens is not None:
                        details["reasoning_tokens"] = usage_details.reasoning_tokens
                logger.record("model_output_truncated", level="WARNING", details=details)
                if retry:
                    raise RunFailure(f"DeepSeek 重试一次后仍达到长度上限（{max_tokens} tokens），本次输出不完整")
                continue
            content = choice.message.content
            if choice.finish_reason != "stop" or not content or not content.strip():
                raise RunFailure("DeepSeek 未返回完整的步骤结果")
            return content.strip()
        raise AssertionError("模型请求应在两次尝试内返回或失败")

    def _request(
        self,
        prompt: str,
        payload: str,
        *,
        json_mode: bool,
        max_tokens: int,
        disable_thinking: bool,
    ) -> ChatCompletion:
        # 仅对官方端点传入 DeepSeek 专用参数，兼容第三方 OpenAI 格式端点。
        extra = (
            {"thinking": {"type": "disabled"}}
            if disable_thinking and self._sdk.base_url.host == "api.deepseek.com"
            else None
        )
        try:
            return self._sdk.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": payload},
                ],
                response_format={"type": "json_object"} if json_mode else {"type": "text"},
                max_tokens=max_tokens,
                extra_body=extra,
            )
        except (AuthenticationError, PermissionDeniedError) as error:
            raise RunFailure("DeepSeek 鉴权失败，请检查服务地址、API 密钥和权限") from error
        except RateLimitError as error:
            raise RunFailure("DeepSeek 请求受限，请检查额度或稍后重试") from error
        except APITimeoutError as error:
            raise RunFailure("DeepSeek 请求超时，请检查网络后重试") from error
        except APIConnectionError as error:
            raise RunFailure("无法连接 DeepSeek，请检查服务地址和网络") from error
        except APIStatusError as error:
            raise RunFailure(f"DeepSeek 请求失败（HTTP {error.status_code}），请检查模型和服务配置") from error
        except OpenAIError as error:
            raise RunFailure("DeepSeek 调用失败，请检查 SDK 和服务配置") from error
