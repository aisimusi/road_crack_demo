from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.agent import tools


def infer_debug_intent(question: str) -> str:
    normalized = question.strip()
    if "这周" in normalized and "上周" in normalized:
        return "compare_crack_stats"
    if any(keyword in normalized for keyword in ("复发", "扩大", "扩展", "复检", "身份档案", "同一裂缝", "维修后")):
        return "crack_identity_tracking"
    if "优先维修" in normalized or "维修清单" in normalized:
        return "maintenance_priority"
    if "最严重" in normalized:
        return "top_severe_cracks"
    if "面积最大" in normalized:
        return "max_area_location"
    if "整体" in normalized or "汇总" in normalized:
        return "campus_summary"
    if tools.extract_road_hint(normalized):
        return "road_scope_analysis"
    return "general_analysis"


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                fragments.append(str(item.get("text") or ""))
        return "".join(fragments)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    role: str
    content: str
    tool_calls: tuple[ToolCallRequest, ...] = ()
    finish_reason: str | None = None


class BaseLLMClient:
    mode = "base"

    def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        runtime: dict[str, Any],
    ) -> LLMResponse:
        raise NotImplementedError

    def stream_generate(
        self,
        *,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        runtime: dict[str, Any],
    ):
        raise NotImplementedError


class OpenAICompatibleLLMClient(BaseLLMClient):
    mode = "live"

    def __init__(
        self,
        api_key: str,
        base_url: str | None,
        model: str | None,
        *,
        request_timeout: float | None = None,
    ):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        if self.base_url.endswith("/chat/completions"):
            self.endpoint = self.base_url
        elif self.base_url.endswith("/v1"):
            self.endpoint = f"{self.base_url}/chat/completions"
        else:
            self.endpoint = f"{self.base_url}/v1/chat/completions"
        self.model = model or "gpt-4.1-mini"
        self.request_timeout = request_timeout or float(os.getenv("OPENAI_TIMEOUT_SECONDS", "90"))

    def _build_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        stream: bool,
        require_tool: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": stream,
        }
        if tools_schema:
            payload["tools"] = tools_schema
            # Some OpenAI-compatible providers only accept "auto" / "none"
            # for tool_choice. We keep enforcement in the agent loop instead.
            payload["tool_choice"] = "auto"
        return payload

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib_request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=self.request_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM 请求失败: HTTP {exc.code} {detail}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"LLM 网络请求失败: {exc.reason}") from exc
        return body if isinstance(body, dict) else {}

    def _parse_message(self, body: dict[str, Any]) -> LLMResponse:
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("LLM 未返回 choices。")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        tool_calls: list[ToolCallRequest] = []
        for item in message.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            function_payload = item.get("function") or {}
            raw_arguments = function_payload.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"LLM 工具参数不是合法 JSON: {raw_arguments}") from exc
            tool_calls.append(
                ToolCallRequest(
                    id=str(item.get("id") or ""),
                    name=str(function_payload.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        return LLMResponse(
            role=str(message.get("role") or "assistant"),
            content=_extract_text_content(message.get("content")),
            tool_calls=tuple(tool_calls),
            finish_reason=str(choice.get("finish_reason")) if choice.get("finish_reason") is not None else None,
        )

    def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        runtime: dict[str, Any],
    ) -> LLMResponse:
        payload = self._build_payload(
            messages=messages,
            tools_schema=tools_schema,
            stream=False,
            require_tool=bool(runtime.get("require_tool")),
        )
        body = self._post_json(payload)
        return self._parse_message(body)

    def stream_generate(
        self,
        *,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        runtime: dict[str, Any],
    ):
        payload = self._build_payload(
            messages=messages,
            tools_schema=tools_schema,
            stream=True,
            require_tool=bool(runtime.get("require_tool")),
        )
        request = urllib_request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        role = "assistant"
        content_parts: list[str] = []
        finish_reason: str | None = None
        tool_calls: dict[int, dict[str, Any]] = {}

        try:
            with urllib_request.urlopen(request, timeout=self.request_timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choice = (chunk.get("choices") or [{}])[0] or {}
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason") or finish_reason
                    if delta.get("role"):
                        role = str(delta.get("role"))
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        yield {"type": "thinking", "content": str(reasoning)}
                    content = delta.get("content")
                    if content:
                        content_parts.append(str(content))
                        yield {"type": "answer", "content": str(content)}

                    for tool_delta in delta.get("tool_calls") or []:
                        if not isinstance(tool_delta, dict):
                            continue
                        index = int(tool_delta.get("index") or 0)
                        entry = tool_calls.setdefault(
                            index,
                            {
                                "id": "",
                                "name": "",
                                "arguments_parts": [],
                            },
                        )
                        if tool_delta.get("id"):
                            entry["id"] = str(tool_delta["id"])
                        function_payload = tool_delta.get("function") or {}
                        if function_payload.get("name"):
                            entry["name"] = str(function_payload["name"])
                        if function_payload.get("arguments"):
                            entry["arguments_parts"].append(str(function_payload["arguments"]))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM 流式请求失败: HTTP {exc.code} {detail}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"LLM 流式网络请求失败: {exc.reason}") from exc

        parsed_tool_calls: list[ToolCallRequest] = []
        for index in sorted(tool_calls):
            entry = tool_calls[index]
            raw_arguments = "".join(entry["arguments_parts"]) or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"LLM 流式工具参数不是合法 JSON: {raw_arguments}") from exc
            parsed_tool_calls.append(
                ToolCallRequest(
                    id=str(entry["id"]),
                    name=str(entry["name"]),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )

        yield {
            "type": "complete",
            "response": LLMResponse(
                role=role,
                content="".join(content_parts),
                tool_calls=tuple(parsed_tool_calls),
                finish_reason=str(finish_reason) if finish_reason is not None else None,
            ),
        }


def build_llm_client(*, model: str | None = None, timeout: float | None = None) -> BaseLLMClient:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，Agent 现已不再提供 Mock LLM 兜底。")
    return OpenAICompatibleLLMClient(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL"),
        model=model or os.getenv("OPENAI_MODEL"),
        request_timeout=timeout,
    )


def build_vision_llm_client() -> BaseLLMClient:
    timeout = float(os.getenv("OPENAI_VISION_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "90")))
    return build_llm_client(
        model=os.getenv("OPENAI_VISION_MODEL") or os.getenv("OPENAI_MODEL"),
        timeout=timeout,
    )
