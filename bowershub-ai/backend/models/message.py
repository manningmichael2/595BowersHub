"""Pydantic models for messages, completions, and streaming."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ModelInfo(BaseModel):
    """Information about an available AI model."""
    id: str
    provider: str  # 'anthropic', 'bedrock', 'ollama'
    display_name: str
    supports_vision: bool = False
    supports_tools: bool = False
    max_output_tokens: int = 4096
    input_cost_per_mtok: Optional[float] = None
    output_cost_per_mtok: Optional[float] = None


class ToolCall(BaseModel):
    """A tool/skill call requested by the model."""
    id: str
    name: str
    arguments: Dict[str, Any]


class CompletionResult(BaseModel):
    """Result from a non-streaming model completion."""
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: Optional[str] = None
    tool_calls: List[ToolCall] = []


class StreamChunk(BaseModel):
    """A single chunk from a streaming response."""
    type: str  # 'text_delta', 'tool_use_start', 'tool_use_delta', 'tool_use_end', 'message_stop', 'usage'
    data: Any = None
    # For text_delta: data = "token text"
    # For tool_use_start: data = {"id": "...", "name": "..."}
    # For tool_use_delta: data = "json fragment"
    # For tool_use_end: data = {"id": "...", "name": "...", "arguments": {...}}
    # For usage: data = {"input_tokens": N, "output_tokens": N}


class MessageResponse(BaseModel):
    """A message as returned to the frontend."""
    id: int
    conversation_id: int
    role: str
    content: str
    attachments: List[Dict[str, Any]] = []
    model_used: Optional[str] = None
    routing_layer: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
