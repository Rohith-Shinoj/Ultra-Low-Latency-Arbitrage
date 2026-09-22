#!/usr/bin/env bash
# Ultra-Low-Latency Arbitrage Infrastructure & Trading Terminal Launcher
# Requires root privileges for kernel-bypass AF_XDP, core isolation, and raw sockets.

if [ "$EUID" -ne 0 ]; then
    echo "Error: ./start.sh requires root privileges for kernel AF_XDP and core pinning." >&2
    echo "Please run: sudo ./start.sh $@" >&2
    exit 1
fi

# Preserve invoking user's python environment and site-packages under sudo
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    for p in "$USER_HOME"/.local/lib/python*/site-packages; do
        if [ -d "$p" ]; then
            export PYTHONPATH="$p${PYTHONPATH:+:$PYTHONPATH}"
        fi
    done
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-compile C++ engine binary if missing
if [ ! -f "$DIR/engine/bin/engine_main" ]; then
    echo "⚡ C++ engine binary not found. Compiling via 'make -C engine'..."
    make -C "$DIR/engine" || exit 1
fi

exec python3 -u "$DIR/scripts/control.py" "$@"
