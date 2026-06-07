"""Pydantic models for conversations and messages."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    workspace_id: int
    title: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    is_archived: Optional[bool] = None


class ConversationListItem(BaseModel):
    id: int
    workspace_id: int
    title: Optional[str] = None
    parent_id: Optional[int] = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationResponse(BaseModel):
    id: int
    workspace_id: int
    user_id: int
    title: Optional[str] = None
    parent_id: Optional[int] = None
    branch_point_msg: Optional[int] = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    messages: List["MessageResponse"] = []


class MessageResponse(BaseModel):
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


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    model: str = "auto"
    attachments: List[Dict[str, Any]] = []
