"""Pydantic models for workspace management."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    system_prompt: str = ""
    default_model: str = "auto"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_context_tokens: int = Field(default=8000, ge=1000, le=100000)
    auto_capture: bool = True
    permitted_schemas: List[str] = []


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    system_prompt: Optional[str] = None
    default_model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_context_tokens: Optional[int] = Field(None, ge=1000, le=100000)
    auto_capture: Optional[bool] = None
    permitted_schemas: Optional[List[str]] = None


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    system_prompt: str
    default_model: str
    temperature: float
    max_context_tokens: int
    auto_capture: bool
    permitted_schemas: List[str]
    created_at: datetime
    user_count: int = 0
    skill_count: int = 0


class WorkspaceUserAssignment(BaseModel):
    user_id: int
    role: str = Field(default="member", pattern="^(owner|member|viewer)$")


class PinnedContextCreate(BaseModel):
    context_type: str = Field(..., pattern="^(static|dynamic)$")
    title: str = Field(..., min_length=1, max_length=200)
    content: Optional[str] = None  # for static
    query: Optional[str] = None  # for dynamic
    refresh_minutes: int = Field(default=60, ge=1, le=1440)
    priority: int = Field(default=100, ge=1, le=1000)


class PinnedContextUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None
    query: Optional[str] = None
    refresh_minutes: Optional[int] = Field(None, ge=1, le=1440)
    priority: Optional[int] = Field(None, ge=1, le=1000)


class PinnedContextResponse(BaseModel):
    id: int
    workspace_id: int
    context_type: str
    title: str
    content: Optional[str] = None
    query: Optional[str] = None
    refresh_minutes: int
    cached_result: Optional[str] = None
    cached_at: Optional[datetime] = None
    priority: int
    token_estimate: int
    created_at: datetime
