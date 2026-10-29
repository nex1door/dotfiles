#!/usr/bin/env bash

# Ожидание готовности X-сервера
sleep 4

export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XAUTHORITY" ]; then
    if [ -f "/run/user/$UID/lyxauth" ]; then
        export XAUTHORITY="/run/user/$UID/lyxauth"
    elif [ -f "$HOME/.Xauthority" ]; then
        export XAUTHORITY="$HOME/.Xauthority"
    fi
fi

# Режим максимальной производительности (Prefer Maximum Performance)
nvidia-settings -a "[gpu:0]/GPUPowerMizerMode=1" > /dev/null 2>&1

# Разгон видеопамяти (+900 MHz)
nvidia-settings -a "[gpu:0]/GPUMemoryTransferRateOffset[3]=900" > /dev/null 2>&1
