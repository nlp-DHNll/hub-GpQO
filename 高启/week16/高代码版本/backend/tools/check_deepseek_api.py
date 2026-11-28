"""单独向 DeepSeek 发送一条问候，检查 API 是否能返回完整回复。"""

import sys

from openai import APIStatusError, OpenAI, OpenAIError

from ..config import load_deepseek_settings
from ..errors import RunFailure


def main() -> int:
    try:
        settings = load_deepseek_settings()
        with OpenAI(
            api_key=settings.api_key, base_url=settings.base_url, timeout=30, max_retries=0,
        ) as sdk:
            extra = {"thinking": {"type": "disabled"}} if sdk.base_url.host == "api.deepseek.com" else None
            print("发送：你好", flush=True)
            response = sdk.chat.completions.create(
                model=settings.model,
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=1024,
                extra_body=extra,
            )
    except RunFailure as error:
        print(str(error), file=sys.stderr)
        return 1
    except APIStatusError as error:
        print(f"DeepSeek 请求失败（HTTP {error.status_code}）", file=sys.stderr)
        return 1
    except OpenAIError as error:
        print(f"DeepSeek 调用失败（{type(error).__name__}）", file=sys.stderr)
        return 1

    if not response.choices:
        print("DeepSeek 未返回模型结果", file=sys.stderr)
        return 1
    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    if choice.finish_reason != "stop" or not content:
        print(f"DeepSeek 未返回完整回复（结束原因：{choice.finish_reason}）", file=sys.stderr)
        return 1

    print(f"回复：{content}")
    print("DeepSeek API 检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
