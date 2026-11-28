"""用模拟的 HTTP 响应检查模型步骤及可读性修正保护。"""

import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import httpx
from openai import OpenAI

from backend.agent.evaluate_content import evaluate_content
from backend.agent.evaluate_readability import evaluate_readability
from backend.agent.generate_report import generate_report
from backend.agent.revise_report import revise_report
from backend.clients.deepseek import DeepSeekClient
from backend.data_models import ReviewIssue, ReviewResult, Source
from backend.enums import StepName, Topic
from backend.errors import RunFailure
from backend.run_tracking import AgentRun
from backend.tools.report_text import BODY_SECTIONS, parse_review, with_sources

MONTH = "2026-10"
OLD_TEXT = "信息情况是节能降耗 12% [S01]。"
NEW_TEXT = "节能降耗 12% [S01]。"
SOURCES = [
    Source(
        "S01", (Topic.INDUSTRY,), "示例公告", "示例机构",
        date(2026, 10, 8), "https://example.invalid/source", "公告写明节能降耗 12%。",
    )
]
BODY = f"# 中国神华 {MONTH} ESG 月报\n\n" + "\n\n".join(
    f"## {section}\n\n{OLD_TEXT if section == '摘要' else '本节示例。'}"
    for section in BODY_SECTIONS
)


class ModelStepsTests(unittest.TestCase):
    def test_truncated_draft_retries_and_keeps_only_complete_output(self) -> None:
        sdk = Mock()
        sdk.base_url = httpx.URL("https://api.deepseek.com")
        create = sdk.chat.completions.create
        create.side_effect = [
            Mock(choices=[Mock(finish_reason="length")], usage=None),
            Mock(choices=[Mock(finish_reason="stop", message=Mock(content=BODY))]),
        ]
        logger = Mock()

        result = generate_report(MONTH, SOURCES, logger, client=DeepSeekClient(sdk, "deepseek-flash"))

        self.assertEqual(result, with_sources(BODY, SOURCES))
        self.assertEqual([call.kwargs["max_tokens"] for call in create.call_args_list], [8192, 16384])
        self.assertEqual(create.call_args_list[0].kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(logger.record.call_args.args[0], "model_output_truncated")

    def test_two_truncated_responses_stop_with_clear_error(self) -> None:
        sdk = Mock()
        sdk.base_url = httpx.URL("https://example.invalid")
        create = sdk.chat.completions.create
        create.return_value = Mock(choices=[Mock(finish_reason="length")], usage=None)

        with self.assertRaisesRegex(RunFailure, "重试一次后"):
            generate_report(MONTH, SOURCES, Mock(), client=DeepSeekClient(sdk, "fixture-model"))

        self.assertEqual(create.call_count, 2)
        self.assertIsNone(create.call_args.kwargs.get("extra_body"))

    def test_sdk_steps_and_targeted_readability_edit(self) -> None:
        issue = {"section": "摘要", "problem": "措辞冗余", "suggestion": "精简句首"}
        outputs = iter((
            BODY,
            json.dumps({"passed": True, "issues": []}),
            json.dumps({"passed": False, "issues": [issue]}),
            json.dumps({"edits": [{"section": "摘要", "before": OLD_TEXT, "after": NEW_TEXT}]}),
            json.dumps({"passed": True, "issues": []}),
        ))
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "fixture",
                    "object": "chat.completion",
                    "model": "fixture-model",
                    "created": 0,
                    "choices": [{
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": next(outputs)},
                    }],
                },
            )

        http = httpx.Client(transport=httpx.MockTransport(respond))
        with OpenAI(api_key="fixture", base_url="https://example.invalid/v1", http_client=http) as sdk:
            client = DeepSeekClient(sdk, "fixture-model")
            logger = Mock()
            draft = generate_report(MONTH, SOURCES, logger, client=client)
            self.assertTrue(evaluate_content(MONTH, draft, SOURCES, logger, client=client).passed)
            review = evaluate_readability(draft, logger, client=client)
            self.assertFalse(review.passed)
            final = revise_report(
                MONTH, draft, SOURCES, review, StepName.EVALUATE_READABILITY, logger, client=client,
            )
            self.assertTrue(evaluate_readability(final, logger, client=client).passed)

        self.assertEqual(final, draft.replace(OLD_TEXT, NEW_TEXT, 1))
        self.assertIn("[S01]: <https://example.invalid/source>", final)
        self.assertEqual(
            [item["response_format"]["type"] for item in requests],
            ["text", "json_object", "json_object", "json_object", "json_object"],
        )
        self.assertEqual(len({item["messages"][0]["content"] for item in requests}), 4)
        self.assertEqual(json.loads(requests[0]["messages"][1]["content"])["sources"][0]["published_on"], "2026-10-08")

    def test_readability_edit_rejects_fact_tokens_changed(self) -> None:
        draft = with_sources(BODY, SOURCES)
        review = ReviewResult(False, (ReviewIssue("摘要", "措辞冗余", "精简句首"),))
        client = Mock()
        client.complete_json.return_value = {
            "edits": [{"section": "摘要", "before": OLD_TEXT, "after": "节能降耗 30% [S01]。"}],
        }
        logger = Mock()
        with self.assertRaisesRegex(RunFailure, "连续 3 次"):
            revise_report(
                MONTH, draft, SOURCES, review, StepName.EVALUATE_READABILITY, logger, client=client,
            )
        self.assertEqual(client.complete_json.call_count, 3)
        self.assertEqual([call.args[0] for call in logger.record.call_args_list], ["revision_rejected"] * 3)

    def test_rejected_edit_retries_with_feedback(self) -> None:
        draft = with_sources(BODY, SOURCES)
        review = ReviewResult(False, (ReviewIssue("摘要", "措辞冗余", "精简句首"),))
        client = Mock()
        client.complete_json.side_effect = [
            {"edits": [{"section": "摘要", "before": OLD_TEXT, "after": "节能降耗 30% [S01]。"}]},
            {"edits": [{"section": "摘要", "before": OLD_TEXT, "after": NEW_TEXT}]},
        ]
        logger = Mock()
        result = revise_report(MONTH, draft, SOURCES, review, StepName.EVALUATE_READABILITY, logger, client=client)
        self.assertEqual(result, draft.replace(OLD_TEXT, NEW_TEXT, 1))
        self.assertEqual(client.complete_json.call_args_list[1].args[1]["retry_reason"], "调整片段改动了章节、数字或引用")
        self.assertEqual(logger.record.call_count, 1)

    def test_failed_revision_does_not_consume_repair_round(self) -> None:
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            run = AgentRun(MONTH, Path(directory), None)
            with self.assertRaisesRegex(RunFailure, "调整失败"), run.step(StepName.REVISE_REPORT, repair_round=1):
                raise RunFailure("调整失败")
            self.assertEqual(run.state.repair_round, 0)

    def test_unknown_citation_is_a_content_issue_before_model_call(self) -> None:
        client = Mock()
        draft = with_sources(BODY.replace("[S01]", "[s99]"), SOURCES)
        review = evaluate_content(MONTH, draft, SOURCES, Mock(), client=client)
        self.assertFalse(review.passed)
        self.assertTrue(any("S99" in issue.problem for issue in review.issues))
        client.complete_json.assert_not_called()

    def test_inconsistent_evaluation_json_is_rejected(self) -> None:
        with self.assertRaises(RunFailure):
            parse_review({"passed": False, "issues": []}, allowed_sections=BODY_SECTIONS)
