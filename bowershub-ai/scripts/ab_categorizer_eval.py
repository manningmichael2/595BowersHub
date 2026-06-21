"""One-off Task-13 model A/B: score the cascade over finance.eval_labels with each
candidate LOCAL categorizer model. Read-only (score_cascade performs no writes).
Run inside the bowershub-ai container (has DB env + the ollama network)."""
import asyncio
import httpx

from backend.config import load_config
from backend.database import close_pool, init_pool
from backend.services.categorization_eval import score_cascade
from backend.services.embeddings import EmbeddingError

OLLAMA = "http://ollama:11434"
MODELS = ["llama3.2:3b", "qwen3:4b", "qwen3:8b"]


class NoEmbed:
    """kNN abstains cleanly — the eval's synthetic descriptors have no merchant
    history, so the LLM tier is what we're comparing."""
    async def embed(self, _t):
        raise EmbeddingError("ab: embeddings disabled")
    async def embed_batch(self, _ts):
        raise EmbeddingError("ab: embeddings disabled")


def make_call(model):
    async def call(prompt):
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                # Mirror production's LLMFallback._default_call_model EXACTLY (num_predict=256,
                # timeout=60→120 headroom) plus think:false — a reasoning model left thinking
                # burns the whole 256-token budget on <think> and emits no JSON (verified:
                # done_reason=length, empty content). think:false is a no-op for non-thinking
                # models, so this is the faithful prod config for all candidates.
                r = await c.post(f"{OLLAMA}/api/chat", json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You classify bank transactions. Return ONLY the JSON object requested."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "num_predict": 256},
                })
                r.raise_for_status()
                return r.json().get("message", {}).get("content", "")
        except Exception as e:
            print("   call error:", e)
            return None
    return call


async def main():
    pool = await init_pool(load_config())
    try:
        for m in MODELS:
            rep = await score_cascade(pool, embeddings_client=NoEmbed(), llm_call_model=make_call(m))
            d = rep.as_dict()
            print(f"\n=== {m} ===")
            print(f"  category accuracy: {d['accuracy']}  ({d['correct']}/{d['total']} correct, {d['abstained']} abstained)")
            print(f"  transfer  P/R    : {d['transfer']['precision']} / {d['transfer']['recall']}")
            print(f"  per_tier         : {d['per_tier']}")
    finally:
        await close_pool()


asyncio.run(main())
