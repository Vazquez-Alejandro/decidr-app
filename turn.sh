#!/bin/bash
# Decidr TURN server manager
CONFIG="$(dirname "$0")/turnserver.conf"
PIDFILE="/tmp/decidr-turn.pid"

case "${1:-status}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "TURN already running (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    nohup turnserver -c "$CONFIG" > /dev/null 2>&1 &
    sleep 0.5
    echo $! > "$PIDFILE"
    echo "TURN server started (PID $(cat "$PIDFILE"))"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null
      rm -f "$PIDFILE"
      echo "TURN server stopped"
    else
      echo "TURN server not running"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "TURN running (PID $(cat "$PIDFILE"))"
    else
      echo "TURN not running"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
