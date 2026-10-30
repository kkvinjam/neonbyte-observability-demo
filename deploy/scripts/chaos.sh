#!/usr/bin/env bash
# Flip NeonByte's fault-injection knobs (SSM parameters read by the services every 30 s).
#   deploy/scripts/chaos.sh latency payments 1500     # +1.5 s on every payments request
#   deploy/scripts/chaos.sh errors catalog 0.2        # 20% HTTP 500s from catalog
#   deploy/scripts/chaos.sh declines 0.5              # 50% card declines (business errors)
#   deploy/scripts/chaos.sh reset                     # everything back to normal
set -euo pipefail
put() { aws ssm put-parameter --overwrite --type String --name "$1" --value "$2" >/dev/null && echo "$1 = $2"; }
case "${1:-}" in
  latency)  put "/neonbyte/chaos/${2:?service}/latency_ms" "${3:?milliseconds}" ;;
  errors)   put "/neonbyte/chaos/${2:?service}/error_rate" "${3:?rate 0-1}" ;;
  declines) put /neonbyte/payments/decline_rate "${2:?rate 0-1}" ;;
  reset)
    for s in storefront catalog cart orders payments; do
      put "/neonbyte/chaos/$s/latency_ms" 0; put "/neonbyte/chaos/$s/error_rate" 0
    done
    put /neonbyte/payments/decline_rate 0.03 ;;
  *) sed -n '2,6p' "$0"; exit 1 ;;
esac
