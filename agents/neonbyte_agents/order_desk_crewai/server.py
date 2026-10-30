"""AgentCore Runtime entrypoint for the Order Desk (CrewAI)."""

from neonbyte_agents.common.agentcore_server import build_app, serve
from neonbyte_agents.order_desk_crewai import run

app = build_app(run)

if __name__ == "__main__":
    serve(app)
