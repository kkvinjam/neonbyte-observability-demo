"""AgentCore Runtime entrypoint for the Concierge (OpenAI Agents SDK)."""

from neonbyte_agents.common.agentcore_server import build_app, serve
from neonbyte_agents.concierge_openai import run

app = build_app(run)

if __name__ == "__main__":
    serve(app)
