"""
Model Provider Abstraction: unified interface to Anthropic, AWS Bedrock, and Ollama.
Discovers available models from each provider dynamically at startup.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List

from backend.config import Config
from backend.models.message import CompletionResult, StreamChunk, ToolCall

logger = logging.getLogger(__name__)


class ModelNotAvailableError(Exception):
    """Raised when a requested model is not available."""
    pass


class BaseProvider(ABC):
    @abstractmethod
    async def complete(self, model, messages, max_tokens, tools=None, system=None) -> CompletionResult: ...
    @abstractmethod
    async def stream(self, model, messages, max_tokens, tools=None, system=None) -> AsyncIterator[StreamChunk]: ...


class AnthropicProvider(BaseProvider):
    """Anthropic API provider using the official SDK."""

    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.api_key = api_key

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        kwargs: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = await self.client.messages.create(**kwargs)

        content_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return CompletionResult(
            content="\n".join(content_parts),
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
            tool_calls=tool_calls,
        )

    async def stream(self, model, messages, max_tokens, tools=None, system=None):
        kwargs: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    btype = getattr(block, "type", None)
                    if btype == "tool_use":
                        # Regular client-side tool — caller will execute it
                        # and feed the result back in a follow-up turn.
                        yield StreamChunk(
                            type="tool_use_start",
                            data={"id": block.id, "name": block.name},
                        )
                    elif btype == "server_tool_use":
                        # Anthropic server-side tool (web_search). The API
                        # is going to execute it inline and continue the
                        # response with the result. We surface this only
                        # so the UI can show "checking the web…" status —
                        # the caller MUST NOT try to run it locally and
                        # MUST NOT loop back for another turn.
                        yield StreamChunk(
                            type="server_tool_use_start",
                            data={
                                "id": getattr(block, "id", ""),
                                "name": getattr(block, "name", "server_tool"),
                            },
                        )
                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield StreamChunk(type="text_delta", data=event.delta.text)
                    elif hasattr(event.delta, "partial_json"):
                        yield StreamChunk(type="tool_use_delta", data=event.delta.partial_json)
                elif event.type == "message_stop":
                    yield StreamChunk(type="message_stop", data=None)

            final_message = await stream.get_final_message()
            yield StreamChunk(
                type="usage",
                data={"input_tokens": final_message.usage.input_tokens,
                      "output_tokens": final_message.usage.output_tokens}
            )


class BedrockProvider(BaseProvider):
    """AWS Bedrock provider using boto3."""

    def __init__(self, access_key: str, secret_key: str, region: str):
        import boto3
        self.runtime = boto3.client(
            "bedrock-runtime",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self.region = region

    def _translate_messages(self, messages: List[Dict]) -> List[Dict]:
        translated = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                translated.append({"role": msg["role"], "content": [{"text": content}]})
            elif isinstance(content, list):
                blocks = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            blocks.append({"text": block["text"]})
                        elif block.get("type") == "image":
                            import base64 as b64
                            data = block["source"]["data"]
                            if isinstance(data, str):
                                data = b64.b64decode(data)
                            blocks.append({
                                "image": {
                                    "format": block["source"]["media_type"].split("/")[1],
                                    "source": {"bytes": data},
                                }
                            })
                        elif block.get("type") == "tool_result":
                            tc = block.get("content", "")
                            if isinstance(tc, list):
                                tc_text = "\n".join(
                                    b.get("text", "") if isinstance(b, dict) else str(b)
                                    for b in tc
                                )
                            else:
                                tc_text = str(tc)
                            blocks.append({"toolResult": {
                                "toolUseId": block["tool_use_id"],
                                "content": [{"text": tc_text}],
                            }})
                        elif block.get("type") == "tool_use":
                            blocks.append({"toolUse": {
                                "toolUseId": block["id"],
                                "name": block["name"],
                                "input": block.get("input", {}),
                            }})
                    else:
                        blocks.append({"text": str(block)})
                translated.append({"role": msg["role"], "content": blocks})
        return translated

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        import asyncio
        kwargs: Dict[str, Any] = {
            "modelId": model,
            "messages": self._translate_messages(messages),
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        if tools:
            kwargs["toolConfig"] = {"tools": [
                {"toolSpec": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": {"json": t.get("input_schema", {"type": "object", "properties": {}})},
                }}
                for t in tools
            ]}

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: self.runtime.converse(**kwargs))

        content_parts = []
        tool_calls = []
        for block in response.get("output", {}).get("message", {}).get("content", []):
            if "text" in block:
                content_parts.append(block["text"])
            elif "toolUse" in block:
                tool_calls.append(ToolCall(
                    id=block["toolUse"]["toolUseId"],
                    name=block["toolUse"]["name"],
                    arguments=block["toolUse"]["input"],
                ))

        usage = response.get("usage", {})
        return CompletionResult(
            content="\n".join(content_parts),
            model=model,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            stop_reason=response.get("stopReason"),
            tool_calls=tool_calls,
        )

    async def stream(self, model, messages, max_tokens, tools=None, system=None):
        import asyncio
        kwargs: Dict[str, Any] = {
            "modelId": model,
            "messages": self._translate_messages(messages),
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        if tools:
            kwargs["toolConfig"] = {"tools": [
                {"toolSpec": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": {"json": t.get("input_schema", {"type": "object", "properties": {}})},
                }}
                for t in tools
            ]}

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: self.runtime.converse_stream(**kwargs))

        current_tool_id = ""
        current_tool_name = ""
        current_tool_input = ""

        for event in response.get("stream", []):
            if "contentBlockStart" in event:
                start = event["contentBlockStart"].get("start", {})
                if "toolUse" in start:
                    current_tool_id = start["toolUse"].get("toolUseId", "")
                    current_tool_name = start["toolUse"].get("name", "")
                    current_tool_input = ""
                    yield StreamChunk(type="tool_use_start",
                                      data={"id": current_tool_id, "name": current_tool_name})
            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    yield StreamChunk(type="text_delta", data=delta["text"])
                elif "toolUse" in delta:
                    fragment = delta["toolUse"].get("input", "")
                    current_tool_input += fragment
                    yield StreamChunk(type="tool_use_delta", data=fragment)
            elif "messageStop" in event:
                yield StreamChunk(type="message_stop", data=None)
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                yield StreamChunk(type="usage", data={
                    "input_tokens": usage.get("inputTokens", 0),
                    "output_tokens": usage.get("outputTokens", 0),
                })


class OllamaProvider(BaseProvider):
    """Ollama local model provider via HTTP API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        import httpx
        from backend.http_client import get_http_client

        ollama_messages = []
        if system:
            ollama_messages.append({"role": "system", "content": system})
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
            ollama_messages.append({"role": msg["role"], "content": content})

        body: Dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                }}
                for t in tools
            ]

        client = get_http_client()
        resp = await client.post(f"{self.base_url}/api/chat", json=body, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        tool_calls = []
        for tc in data.get("message", {}).get("tool_calls", []):
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=tc["function"]["name"],
                arguments=tc["function"].get("arguments", {}),
            ))

        return CompletionResult(
            content=content,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            stop_reason="stop",
            tool_calls=tool_calls,
        )

    async def stream(self, model, messages, max_tokens, tools=None, system=None):
        import httpx
        from backend.http_client import get_http_client

        ollama_messages = []
        if system:
            ollama_messages.append({"role": "system", "content": system})
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
            ollama_messages.append({"role": msg["role"], "content": content})

        body: Dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }

        client = get_http_client()
        async with client.stream("POST", f"{self.base_url}/api/chat", json=body) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done"):
                    yield StreamChunk(type="usage", data={
                        "input_tokens": data.get("prompt_eval_count", 0),
                        "output_tokens": data.get("eval_count", 0),
                    })
                    yield StreamChunk(type="message_stop", data=None)
                elif "message" in data:
                    token = data["message"].get("content", "")
                    if token:
                        yield StreamChunk(type="text_delta", data=token)


class ModelProvider:
    """
    Unified interface to all model providers.
    Caches the model list and refreshes on demand.
    """

    def __init__(self, config: Config):
        self.config = config
        self.providers: Dict[str, BaseProvider] = {}

        if config.ANTHROPIC_API_KEY:
            self.providers["anthropic"] = AnthropicProvider(config.ANTHROPIC_API_KEY)
            logger.info("  ✓ Anthropic provider initialized")

        if config.aws_enabled:
            try:
                self.providers["bedrock"] = BedrockProvider(
                    config.AWS_ACCESS_KEY_ID,
                    config.AWS_SECRET_ACCESS_KEY,
                    config.AWS_REGION or "us-east-1",
                )
                logger.info("  ✓ Bedrock provider initialized")
            except Exception as e:
                logger.warning(f"  ✗ Bedrock init failed: {e}")

        if config.ollama_enabled:
            self.providers["ollama"] = OllamaProvider(config.OLLAMA_URL)
            logger.info(f"  ✓ Ollama provider initialized ({config.OLLAMA_URL})")

        if not self.providers:
            logger.warning("  ⚠ No model providers configured!")

    def _resolve_provider(self, model: str) -> BaseProvider:
        """Determine which provider handles a given model ID."""
        if model.startswith("claude") and "anthropic" in self.providers:
            return self.providers["anthropic"]
        elif (model.startswith("us.") or model.startswith("amazon.") or model.startswith("anthropic.")) and "bedrock" in self.providers:
            return self.providers["bedrock"]
        elif "ollama" in self.providers and ":" in model:
            return self.providers["ollama"]
        elif "anthropic" in self.providers:
            return self.providers["anthropic"]
        raise ModelNotAvailableError(f"No provider available for model: {model}")

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        provider = self._resolve_provider(model)
        return await provider.complete(model, messages, max_tokens, tools, system)

    async def stream(self, model, messages, max_tokens, tools=None, system=None):
        provider = self._resolve_provider(model)
        async for chunk in provider.stream(model, messages, max_tokens, tools, system):
            yield chunk

    def get_default_chat_model(self) -> str:
        """Return the default chat model, resolved from the DB-backed catalog (R4.4)."""
        from backend.services.model_catalog import default_chat_model
        return default_chat_model()
