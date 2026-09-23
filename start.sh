#!/usr/bin/env bash
# Ultra-Low-Latency Arbitrage Infrastructure & Trading Terminal Launcher
# Runs directly as standard user (no sudo required).

# Preserve invoking user's python environment and site-packages under sudo
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    for p in "$USER_HOME"/.local/lib/python*/site-packages; do
        if [ -d "$p" ]; then
            export PYTHONPATH="$p${PYTHONPATH:+:$PYTHONPATH}"
        fi
    done
    for bin_dir in "$USER_HOME/.kx/bin" "$USER_HOME/q/bin" "$USER_HOME/.local/bin"; do
        if [ -d "$bin_dir" ]; then
            export PATH="$bin_dir:$PATH"
        fi
    done
    if [ -d "$USER_HOME/.kx" ]; then
        export QHOME="${QHOME:-$USER_HOME/.kx/q}"
        export QLIC="${QLIC:-$USER_HOME/.kx}"
    fi
fi

# Fallback for standard ubuntu user installation if not invoked via SUDO_USER
for bin_dir in "/home/ubuntu/.kx/bin" "/home/ubuntu/.local/bin"; do
    if [ -d "$bin_dir" ] && [[ ":$PATH:" != *":$bin_dir:"* ]]; then
        export PATH="$bin_dir:$PATH"
    fi
done
if [ -d "/home/ubuntu/.kx" ]; then
    export QHOME="${QHOME:-/home/ubuntu/.kx/q}"
    export QLIC="${QLIC:-/home/ubuntu/.kx}"
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-compile C++ engine binary if missing
if [ ! -f "$DIR/engine/bin/engine_main" ]; then
    echo "⚡ C++ engine binary not found. Compiling via 'make -C engine'..."
    make -C "$DIR/engine" || exit 1
fi

exec python3 -u "$DIR/scripts/control.py" "$@"
