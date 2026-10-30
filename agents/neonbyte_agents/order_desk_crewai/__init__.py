"""Order Desk sub-agent (CrewAI)."""

import os

# Disable CrewAI telemetry here, before .agent imports crewai; this agent deploys on its own.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from neonbyte_agents.order_desk_crewai.agent import run  # noqa: E402

__all__ = ["run"]
