#!/usr/bin/env bash
# install.sh — раскладывает конфиги из этого репозитория по $HOME.
#
#   ./install.sh                 всё, кроме xfconf-каналов (их ставят отдельно)
#   ./install.sh --dry-run       только показать, что будет скопировано
#   ./install.sh --only picom,eww  отдельные группы
#   ./install.sh --with-xfconf   дополнительно перезаписать каналы xfconf
#                                (панель, хоткеи, обои — с бэкапом, нужен релогин)
#
# Принципы:
#   * ничего не удаляет: существующий файл сначала копируется в
#     ~/.dotfiles-backup-<дата_время>/ с тем же относительным путём;
#   * подставляет @@HOME@@ → $HOME (в .desktop/.xml/подобных путях переменные
#     не раскрываются, поэтому в репозитории стоит плейсхолдер);
#   * root не нужен и не используется.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP="$HOME/.dotfiles-backup-$STAMP"
DRY=0
WITH_XFCONF=0
ONLY=""

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,12p' "$ROOT/install.sh" | sed 's/^# \{0,1\}//'
}

want() { # имя группы запрошено пользователем?
  [ -z "$ONLY" ] && return 0
  case ",$ONLY," in *",$1,"*) return 0 ;; esac
  return 1
}

put() { # <путь в репозитории> <куда> [права]
  local src="$ROOT/$1" dst="$2" mode="${3:-644}"
  [ -f "$src" ] || { warn "в репозитории нет $1"; return 0; }
  if [ "$DRY" = 1 ]; then
    printf '  [dry] %-46s → %s\n' "$1" "${dst/#$HOME/\~}"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    mkdir -p "$BACKUP/$(dirname "${dst#"$HOME"/}")"
    cp -a "$dst" "$BACKUP/${dst#"$HOME"/}"
  fi
  if grep -q '@@HOME@@' "$src" 2>/dev/null; then
    sed "s|@@HOME@@|$HOME|g" "$src" > "$dst"
  else
    cp -f "$src" "$dst"
  fi
  chmod "$mode" "$dst"
  printf '  %-46s → %s\n' "$1" "${dst/#$HOME/\~}"
}

group_shell() {
  say "оболочки: bash, zsh, fish"
  put config/shell/bashrc       "$HOME/.bashrc"
  put config/shell/bash_profile "$HOME/.bash_profile"
  put config/shell/zshrc        "$HOME/.zshrc"
  put config/fish/config.fish   "$HOME/.config/fish/config.fish"
  put config/fish/functions/agy.fish "$HOME/.config/fish/functions/agy.fish"
}

group_terminal() {
  say "терминал: fastfetch, btop, micro"
  put config/fastfetch/config.jsonc  "$HOME/.config/fastfetch/config.jsonc"
  put config/fastfetch/ava.ansi      "$HOME/.config/fastfetch/ava.ansi"
  put config/fastfetch/make_logo.sh  "$HOME/.config/fastfetch/make_logo.sh" 755
  put config/fastfetch/gen_logo.py   "$HOME/.config/fastfetch/gen_logo.py"  755
  put config/btop/btop.conf          "$HOME/.config/btop/btop.conf"
  put config/micro/settings.json     "$HOME/.config/micro/settings.json"
}

group_picom() {
  say "picom: конфиги и переключатель"
  put config/picom/picom.conf            "$HOME/.config/picom/picom.conf"
  put config/picom/picom-animations.conf "$HOME/.config/picom/picom-animations.conf"
  put scripts/picom-toggle.sh            "$HOME/.local/bin/picom-toggle.sh" 755
}

group_eww() {
  say "Eww: верхняя панель"
  local f
  for f in eww.yuck eww.scss generated.yuck; do
    put "config/eww/$f" "$HOME/.config/eww/$f"
  done
  put config/eww/scripts/bridge.py            "$HOME/.config/eww/scripts/bridge.py" 755
  put config/eww/scripts/restore-shortcuts.py "$HOME/.config/eww/scripts/restore-shortcuts.py" 755
  put config/eww/assets/apple.svg             "$HOME/.config/eww/assets/apple.svg"
  put config/eww/assets/wallhaven.svg         "$HOME/.config/eww/assets/wallhaven.svg"
  put local/bin/eww-topbar                    "$HOME/.local/bin/eww-topbar" 755
  put config/autostart/eww-topbar.desktop     "$HOME/.config/autostart/eww-topbar.desktop"
}

group_xfce() {
  say "XFCE: настройки, ярлыки, док, оформление"
  put config/xfce4/helpers.rc          "$HOME/.config/xfce4/helpers.rc"
  put config/xfce4/xfce4-screenshooter "$HOME/.config/xfce4/xfce4-screenshooter"
  put config/mimeapps.list             "$HOME/.config/mimeapps.list"
  put config/user-dirs.dirs            "$HOME/.config/user-dirs.dirs"
  put config/autostart/picom.desktop   "$HOME/.config/autostart/picom.desktop"
  put config/autostart/plank.desktop   "$HOME/.config/autostart/plank.desktop"
  put config/autostart/nvidia-oc.desktop "$HOME/.config/autostart/nvidia-oc.desktop"
  local f
  for f in config/plank/dock1/launchers/*.dockitem; do
    put "$f" "$HOME/.config/plank/dock1/launchers/$(basename "$f")"
  done
  if command -v update-desktop-database >/dev/null; then
    [ "$DRY" = 1 ] || update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
  fi
}

group_services() {
  say "systemd --user: юниты"
  local f
  for f in config/systemd/user/*.service; do
    put "$f" "$HOME/.config/systemd/user/$(basename "$f")"
  done
  if [ "$DRY" = 0 ] && command -v systemctl >/dev/null; then
    systemctl --user daemon-reload || true
    echo "  включить: systemctl --user enable --now smart-clipboard.service"
  fi
}

group_bin() {
  say "локальные обёртки в ~/.local/bin"
  local f
  for f in local/bin/*; do
    put "$f" "$HOME/.local/bin/$(basename "$f")" 755
  done
}

group_theme() {
  say "переключатель тем XFCE"
  # Скрипты ищут профили в ~/dotfiles (DOTFILES_DIR). Репозиторий должен лежать там,
  # поэтому при установке из другого места делаем ссылку, а не копию.
  if [ "$ROOT" != "$HOME/dotfiles" ]; then
    if [ -L "$HOME/dotfiles" ]; then
      warn "~/.dotfiles уже ссылка на $(readlink "$HOME/dotfiles") — оставляю как есть"
    elif [ -d "$HOME/dotfiles" ]; then
      warn "есть отдельный каталог ~/dotfiles — скопируй в него вручную:"
      warn "  cp -a '$ROOT/scripts' '$ROOT/profiles' '$ROOT/launchers' ~/dotfiles/"
    elif [ "$DRY" = 1 ]; then
      echo "  [dry] ~/.dotfiles → $ROOT"
    else
      ln -s "$ROOT" "$HOME/dotfiles"
      echo "  ~/.dotfiles → $ROOT"
    fi
  fi
  put launchers/theme-switch.desktop "$HOME/.local/share/applications/theme-switch.desktop"
}

group_xfconf() {
  [ "$WITH_XFCONF" = 1 ] || return 0
  say "каналы xfconf (панель, хоткеи, обои) — после установки нужен relogin"
  local f
  for f in config/xfce4/xfconf/xfce-perchannel-xml/*.xml; do
    put "$f" "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/$(basename "$f")"
  done
  warn "запущенный xfconfd может затереть файлы: выйди и войди в сеанс заново"
}

main() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)     DRY=1 ;;
      --with-xfconf) WITH_XFCONF=1 ;;
      --only)        ONLY="${2:-}"; shift ;;
      -h|--help)     usage; exit 0 ;;
      *) die "неизвестный флаг: $1 (см. --help)" ;;
    esac
    shift
  done

  [ "$DRY" = 1 ] || mkdir -p "$BACKUP"
  [ "$DRY" = 1 ] && say "пробный прогон: ничего не записываю"

  want shell    && group_shell
  want terminal && group_terminal
  want picom    && group_picom
  want eww      && group_eww
  want xfce     && group_xfce
  want services && group_services
  want bin      && group_bin
  want theme    && group_theme
  group_xfconf

  say "готово"
  [ "$DRY" = 1 ] || echo "  бэкап прежних файлов: ${BACKUP/#$HOME/\~}"
  echo "  проверить: ~/dotfiles/scripts/theme-switch.sh show"
}

main "$@"
