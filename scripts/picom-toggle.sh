#!/usr/bin/env bash
# picom-toggle.sh — включить/выключить picom в один шаг и согласовать его
# со встроенным композитором xfwm4 (два композитора одновременно конфликтуют).
#
#   picom-toggle.sh            переключить (это и висит на Win+P)
#   picom-toggle.sh on|off     явно включить/выключить
#   picom-toggle.sh status     состояние
#
# Конфиг выбирается автоматически: обычный picom → config/picom/picom.conf,
# форк с анимациями (ft-labs, pijulius, compfy…) → config/picom/picom-animations.conf.
set -uo pipefail

DOTFILES_DIR="${DOTFILES_DIR:-$HOME/dotfiles}"
CONF_DIR="$HOME/.config/picom"
SRC_CONF_DIR="$DOTFILES_DIR/config/picom"
LOG="$HOME/.cache/picom.log"
PIDFILE="$HOME/.cache/picom.pid"

notify() {
  command -v notify-send >/dev/null || return 0
  notify-send -a "picom" -i video-display "$1" "${2:-}" >/dev/null 2>&1 || true
}
compositing() { xfconf-query -c xfwm4 -p /general/use_compositing -s "$1" 2>/dev/null || true; }

picom_bin() { command -v picom 2>/dev/null || { [ -x "$HOME/.local/bin/picom" ] && echo "$HOME/.local/bin/picom"; }; }

picom_pid() {
  local pid=""
  if [ -s "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && grep -qa picom "/proc/$pid/cmdline" 2>/dev/null; then
      printf '%s' "$pid"; return 0
    fi
  fi
  pid=$(pgrep -x picom 2>/dev/null | head -1)
  [ -n "$pid" ] && { printf '%s' "$pid"; return 0; }
  return 1
}
running() { picom_pid >/dev/null; }

is_animation_fork() {
  local bin; bin=$(picom_bin) || return 1
  "$bin" --version 2>&1 | grep -qiE 'pijulius|ft.?labs|arian|compfy|simpleanims|yaoccc|animations'
}

pick_config() {
  local cfg="$SRC_CONF_DIR/picom.conf"
  if is_animation_fork && [ -f "$SRC_CONF_DIR/picom-animations.conf" ]; then
    cfg="$SRC_CONF_DIR/picom-animations.conf"
  fi
  printf '%s' "$cfg"
}

start_picom() {
  local bin; bin=$(picom_bin)
  if [ -z "$bin" ]; then
    notify "picom не установлен" "поставь: sudo pacman -S picom"
    return 1
  fi
  mkdir -p "$CONF_DIR" "$(dirname "$LOG")"
  local cfg; cfg=$(pick_config)
  if [ ! -f "$cfg" ]; then
    notify "нет конфига picom" "ожидался: $cfg"
    return 1
  fi
  cp -f "$SRC_CONF_DIR"/*.conf "$CONF_DIR"/ 2>/dev/null || true
  compositing false                 # освобождаем место под picom
  pkill -x picom >/dev/null 2>&1 || true
  sleep 0.4
  setsid -f "$bin" --config "$cfg" --log-file "$LOG" --write-pid-path "$PIDFILE"
  sleep 1.5
  if running; then
    notify "picom включён" "$(basename "$cfg") · выключить: Win+P"
    return 0
  fi
  compositing false
  notify "picom не запустился" "смотри $LOG"
  return 1
}

stop_picom() {
  pkill -x picom >/dev/null 2>&1 || true
  rm -f "$PIDFILE"
  compositing false                 # не включаем xfwm4 — без композитора
  notify "picom выключен" "композитор полностью выключен · включить: Win+P"
}

case "${1:-toggle}" in
  on)
    if running; then
      compositing false                 # если профиль вернул композитор xfwm4 — убираем конфликт
      notify "picom уже работает" "выключить: Win+P"
      exit 0
    fi
    start_picom ;;
  off)
    if ! running; then notify "picom уже выключен" "включить: Win+P"; exit 0; fi
    stop_picom ;;
  toggle)
    if running; then stop_picom; else start_picom; fi ;;
  status)
    if running; then
      echo "picom: работает (pid $(picom_pid)), конфиг: $(pick_config)"
      echo "       лог: $LOG"
    else
      echo "picom: выключен · композитинг xfwm4: $(xfconf-query -c xfwm4 -p /general/use_compositing 2>/dev/null)"
    fi ;;
  *) echo "использование: picom-toggle.sh [on|off|toggle|status]" >&2; exit 2 ;;
esac