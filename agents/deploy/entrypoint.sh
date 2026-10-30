#!/bin/sh
# Start one agent under ADOT auto-instrumentation.
set -e
case "$AGENT" in
  orchestrator) MODULE=neonbyte_agents.orchestrator_strands.server ;;
  advisor)      MODULE=neonbyte_agents.product_advisor_langgraph.server ;;
  orderdesk)    MODULE=neonbyte_agents.order_desk_crewai.server ;;
  support)      MODULE=neonbyte_agents.support_llamaindex.server ;;
  concierge)    MODULE=neonbyte_agents.concierge_openai.server ;;
  *) echo "unknown AGENT '$AGENT'" >&2; exit 1 ;;
esac
# Append, never set: AgentCore injects service.name and aws.log.group.names into this same variable.
export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES:+$OTEL_RESOURCE_ATTRIBUTES,}service.namespace=neonbyte"
exec opentelemetry-instrument python -m "$MODULE"
