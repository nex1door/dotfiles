#!/usr/bin/env python3
"""Undo only shortcuts installed by this topbar; keep later user edits."""
import json
from pathlib import Path
import subprocess

state = Path.home() / '.local/state/eww-topbar/shortcuts-added.json'
if state.exists():
    for key, expected in json.loads(state.read_text()).items():
        command = ['xfconf-query', '-c', 'xfce4-keyboard-shortcuts', '-p', key]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip() == expected:
            subprocess.run(command + ['-r'], check=True)
