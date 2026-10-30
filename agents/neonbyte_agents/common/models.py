"""Single source of truth for which model each agent uses.

Same palette as the One Observability Demo's Waggle agents: four providers on
Amazon Bedrock (Anthropic · Amazon · Meta · OpenAI-OSS), all via SigV4.
"""

from __future__ import annotations

import os

from neonbyte_agents.common import config

# --- Model palette; override any via env.
SONNET_4_6 = config.CLAUDE_MODEL_ID  # backbone Claude, from config (BEDROCK_CLAUDE_MODEL_ID)
NOVA_2_LITE = os.getenv("BEDROCK_NOVA_LITE_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
LLAMA_4_MAVERICK = os.getenv("BEDROCK_LLAMA_MODEL_ID", "us.meta.llama4-maverick-17b-instruct-v1:0")
GPT_OSS = config.GPT_OSS_MODEL_ID  # from config (BEDROCK_GPT_OSS_MODEL_ID)

# --- Per-agent assignment (env override wins), tiered by task cost: capable models for reasoning only.
AGENT_MODELS: dict[str, str] = {
    "orchestrator": os.getenv("ORCHESTRATOR_MODEL_ID", SONNET_4_6),  # routing / reasoning
    "advisor": os.getenv("ADVISOR_MODEL_ID", SONNET_4_6),  # product comparison, reasoning-heavy
    "orderdesk": os.getenv("ORDERDESK_MODEL_ID", NOVA_2_LITE),  # lightweight tool calls
    "support": os.getenv("SUPPORT_MODEL_ID", LLAMA_4_MAVERICK),  # LlamaIndex on Llama 4
    "concierge": os.getenv("CONCIERGE_MODEL_ID", GPT_OSS),  # OpenAI SDK on gpt-oss
}


def model_id(agent: str) -> str:
    """Return the Bedrock model id assigned to `agent`."""
    try:
        return AGENT_MODELS[agent]
    except KeyError:
        raise KeyError(f"Unknown agent '{agent}'. Known: {sorted(AGENT_MODELS)}") from None


def litellm_model(agent: str) -> str:
    """Return the LiteLLM-style id (``bedrock/<model-id>``) for CrewAI and the OpenAI Agents SDK."""
    return f"bedrock/{model_id(agent)}"
