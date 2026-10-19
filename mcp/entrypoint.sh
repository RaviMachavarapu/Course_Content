#!/bin/sh
# Boots a virtual display + a web-viewable VNC session before running
# whatever command the container was actually asked to run (the shim server
# normally, or `npx notebooklm-mcp-server auth` for the one-time interactive
# Google login — see mcp/README.md).
#
# This exists because `notebooklm-mcp-server auth` opens a real Chromium
# window, and this container has no physical screen. Xvfb fakes one;
# x11vnc + noVNC let you watch and click through it from an ordinary browser
# tab at http://localhost:6080/vnc.html.
set -e

export DISPLAY=:99
Xvfb "$DISPLAY" -screen 0 1280x800x24 >/var/log/xvfb.log 2>&1 &

# give Xvfb a moment to bind before anything tries to connect to it
for _ in 1 2 3 4 5; do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

x11vnc -display "$DISPLAY" -nopw -forever -shared -rfbport 5900 \
  >/var/log/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 6080 localhost:5900 \
  >/var/log/novnc.log 2>&1 &

exec "$@"
