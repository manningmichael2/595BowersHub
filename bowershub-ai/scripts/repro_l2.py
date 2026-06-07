import asyncio
import os
import sys
sys.path.insert(0, "/app")

from backend.services.router_engine import RouterEngine, RoutingContext
from backend.services.skill_executor import SkillExecutor
from backend.services.model_provider import ModelProvider
from backend.config import Config
from backend.database import init_pool


class FakeWS:
    async def send_typing(self, *a, **k): pass
    async def send_token(self, *a, **k): pass
    async def send_skill_status(self, *a, **k): pass
    async def stream_to_user(self, *a, **k): pass


async def go():
    config = Config()
    pool = await init_pool(config)
    mp = ModelProvider(config)
    se = SkillExecutor(config)
    router = RouterEngine(mp, se, config)
    ctx = RoutingContext(
        user_id=1, user_role="admin",
        workspace_id=3, workspace_name="Woodshop",
        system_prompt="You are a woodshop assistant.",
        default_model="auto", max_context_tokens=80000,
        permitted_schemas=["inventory", "files"],
        conversation_id=999,
    )
    result = await router.route("how many router bits do i have?", ctx, FakeWS())
    print("layer:", result.layer)
    print("---")
    print(result.content)


asyncio.run(go())
