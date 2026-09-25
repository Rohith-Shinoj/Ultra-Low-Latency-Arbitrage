#!/usr/bin/env bash
# Ultra-Low-Latency Arbitrage Infrastructure & Trading Terminal Launcher
# Runs directly as standard user (no sudo required).

# Ensure python environment, site-packages, and binaries (q, kdb) are accessible
TARGET_HOME="$HOME"
if [ -n "$SUDO_USER" ]; then
    SUDO_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    [ -n "$SUDO_HOME" ] && TARGET_HOME="$SUDO_HOME"
fi

for uh in "$TARGET_HOME" "/home/ubuntu"; do
    if [ -d "$uh" ]; then
        for p in "$uh"/.local/lib/python*/site-packages; do
            if [ -d "$p" ]; then
                export PYTHONPATH="$p${PYTHONPATH:+:$PYTHONPATH}"
            fi
        done
        if [ -f "$uh/.kx/kc.lic" ] || [ -f "$uh/.kx/k4.lic" ]; then
            export QHOME="${QHOME:-$uh/.kx/q}"
            export QLIC="${QLIC:-$uh/.kx}"
            export PATH="$uh/.kx/bin:$PATH"
        elif [ -d "$uh/q" ]; then
            export QHOME="${QHOME:-$uh/q}"
            export QLIC="${QLIC:-$uh/q}"
        elif [ -d "$uh/.kx" ]; then
            export QHOME="${QHOME:-$uh/.kx/q}"
            export QLIC="${QLIC:-$uh/.kx}"
        fi
        for bin_dir in "$uh/.kx/bin" "$uh/q/l64" "$uh/q/bin" "$uh/.local/bin" "$uh/bin"; do
            if [ -d "$bin_dir" ] && [[ ":$PATH:" != *":$bin_dir:"* ]]; then
                export PATH="$bin_dir:$PATH"
            fi
        done
    fi
done

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-compile C++ engine binary if missing
if [ ! -f "$DIR/engine/bin/engine_main" ]; then
    echo "⚡ C++ engine binary not found. Compiling via 'make -C engine'..."
    make -C "$DIR/engine" || exit 1
fi

exec python3 -u "$DIR/scripts/control.py" "$@"
