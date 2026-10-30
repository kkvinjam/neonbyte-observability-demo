"""AgentCore Runtime entrypoint for Customer Support (LlamaIndex)."""

from neonbyte_agents.common.agentcore_server import build_app, serve
from neonbyte_agents.support_llamaindex import run

app = build_app(run)

if __name__ == "__main__":
    serve(app)
