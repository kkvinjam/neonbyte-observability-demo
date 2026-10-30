"""AgentCore Runtime entrypoint for the Product Advisor (LangGraph)."""

from neonbyte_agents.common.agentcore_server import build_app, serve
from neonbyte_agents.product_advisor_langgraph import run

app = build_app(run)

if __name__ == "__main__":
    serve(app)
