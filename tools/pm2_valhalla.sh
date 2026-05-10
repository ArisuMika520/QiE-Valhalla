#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/ecosystem.config.cjs"
APPS=(qie-valhalla-watch qie-valhalla-dashboard)

usage() {
  cat <<'EOF'
Usage: tools/pm2_valhalla.sh <command> [pm2 args]

Commands:
  start             Start watcher and dashboard
  start-watch       Start watcher only
  start-dashboard   Start dashboard only
  stop              Stop watcher and dashboard
  restart           Restart watcher and dashboard with updated environment
  delete            Remove watcher and dashboard from PM2
  status            Show PM2 process status
  logs [app]        Tail logs; defaults to qie-valhalla-watch
  save              Save current PM2 process list for boot resurrection

Examples:
  tools/pm2_valhalla.sh start
  tools/pm2_valhalla.sh logs --lines 100
  tools/pm2_valhalla.sh stop
EOF
}

run_for_apps() {
  local action="$1"
  shift
  local found=0

  for app in "${APPS[@]}"; do
    if pm2 describe "$app" >/dev/null 2>&1; then
      pm2 "$action" "$app" "$@"
      found=1
    fi
  done

  if [[ "$found" -eq 0 ]]; then
    printf 'No QiE Valhalla PM2 processes found.\n'
  fi
}

command="${1:-status}"
shift || true

case "$command" in
  start)
    pm2 start "$CONFIG" "$@"
    ;;
  start-watch)
    pm2 start "$CONFIG" --only qie-valhalla-watch "$@"
    ;;
  start-dashboard)
    pm2 start "$CONFIG" --only qie-valhalla-dashboard "$@"
    ;;
  stop)
    run_for_apps stop "$@"
    ;;
  restart)
    pm2 restart "$CONFIG" --update-env "$@"
    ;;
  delete|remove)
    run_for_apps delete "$@"
    ;;
  status|list|ls)
    pm2 status "$@"
    ;;
  logs)
    if [[ "$#" -eq 0 || "${1:0:1}" == "-" ]]; then
      pm2 logs qie-valhalla-watch "$@"
    else
      pm2 logs "$@"
    fi
    ;;
  save)
    pm2 save "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac