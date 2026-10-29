#!/usr/bin/env bash
# lib-theme.sh — общие функции для переключения оформления XFCE.
# Подключается из theme-switch.sh / theme-menu.sh. Напрямую не запускается.
# Хост: CachyOS + XFCE 4.20, X11, локаль ru_RU.

DOTFILES_DIR="${DOTFILES_DIR:-$HOME/dotfiles}"
PROFILES_DIR="$DOTFILES_DIR/profiles"
STATE_DIR="$DOTFILES_DIR/.state"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

notify() { # заголовок, текст
  command -v notify-send >/dev/null || return 0
  notify-send -a "Оформление XFCE" -i preferences-desktop-theme "$1" "${2:-}" >/dev/null 2>&1 || true
}

# ── xfconf ─────────────────────────────────────────────────────────────────────
xfconf_has() { xfconf-query -c "$1" -p "$2" >/dev/null 2>&1; }

xfconf_set() { # канал, свойство, тип, значение
  local ch="$1" prop="$2" type="$3" val="$4"
  if xfconf_has "$ch" "$prop"; then
    xfconf-query -c "$ch" -p "$prop" -s "$val" 2>/dev/null || warn "не записалось: $ch$prop"
  else
    xfconf-query -c "$ch" -p "$prop" -n -t "$type" -s "$val" 2>/dev/null || warn "не создалось: $ch$prop"
  fi
}

apply_xfconf_tsv() { # файл: канал:::свойство:::тип:::значение  (# — комментарий)
  local f="$1" ch prop type val rest line
  [ -f "$f" ] || { warn "нет файла настроек: $f"; return 0; }
  while IFS= read -r line; do
    case "${line:-}" in ''|\#*) continue ;; esac
    [ "${line}" = "${line/:::/}" ] && continue
    ch=${line%%:::*};      rest=${line#*:::}
    prop=${rest%%:::*};    rest=${rest#*:::}
    type=${rest%%:::*};    val=${rest#*:::}
    [ -n "$ch" ] && [ -n "$prop" ] || continue
    xfconf_set "$ch" "$prop" "$type" "$val"
  done < "$f"
}

list_channels() { xfconf-query -l 2>/dev/null | tr -d ' ' | grep -v ':$' | grep -v '^$' | sort -u; }

# ── снимок состояния (то, что стоит сейчас) ────────────────────────────────────
snapshot_state() { # каталог-назначение
  local dest="$1"
  mkdir -p "$dest/xfconf-xml" "$dest/xfconf-dump" "$dest/config"
  local chan
  while read -r chan; do
    [ -n "$chan" ] || continue
    xfconf-query -c "$chan" -lv > "$dest/xfconf-dump/${chan}.txt" 2>/dev/null || true
  done < <(list_channels)
  cp -a "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/." "$dest/xfconf-xml/" 2>/dev/null || true
  cp -a "$HOME/.config/xfce4/panel"                        "$dest/config/" 2>/dev/null || true
  cp -a "$HOME/.config/autostart"                          "$dest/config/" 2>/dev/null || true
  cp -a "$HOME/.config/gtk-3.0"                            "$dest/config/" 2>/dev/null || true
  {
    echo "host=$(hostname)"
    echo "btime=$(date '+%F %T %z')"
    echo "gtk_theme=$(xfconf-query -c xsettings -p /Net/ThemeName 2>/dev/null)"
    echo "icon_theme=$(xfconf-query -c xsettings -p /Net/IconThemeName 2>/dev/null)"
    echo "cursor_theme=$(xfconf-query -c xsettings -p /Gtk/CursorThemeName 2>/dev/null)"
    echo "gtk_font=$(xfconf-query -c xsettings -p /Gtk/FontName 2>/dev/null)"
    echo "xfwm_theme=$(xfconf-query -c xfwm4 -p /general/theme 2>/dev/null)"
    echo "xfwm_layout=$(xfconf-query -c xfwm4 -p /general/button_layout 2>/dev/null)"
  } > "$dest/inventory.txt"
  xfconf-query -c xfce4-desktop -lv 2>/dev/null | grep last-image > "$dest/wallpapers.txt" || true
  echo "$dest"
}

restore_xml_state() { # профиль-снимок с xfconf-xml/
  local src="$1"
  [ -d "$src/xfconf-xml" ] || die "в профиле нет xfconf-xml/: $src"
  pkill -x picom >/dev/null 2>&1 || true      # снимок вернёт и настройку композитора
  rm -f "$HOME/.config/autostart/picom.desktop"
  stop_panel
  cp -a "$src/xfconf-xml/." "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/"
  pkill -x xfconfd >/dev/null 2>&1 || true
  sleep 1
  start_panel
  [ -d "$src/config/autostart" ] && { rm -rf "$HOME/.config/autostart"; cp -a "$src/config/autostart" "$HOME/.config/autostart"; }
  xfdesktop --reload >/dev/null 2>&1 || true
}

# ── панель ─────────────────────────────────────────────────────────────────────
stop_panel() {
  if [ -f "$HOME/.config/eww/enabled" ]; then
    systemctl --user stop eww-topbar.service eww-tray-bridge.service || true
  fi
  xfce4-panel -q >/dev/null 2>&1 || true
  local i
  for i in 1 2 3 4 5 6; do pgrep -x xfce4-panel >/dev/null || break; sleep 0.4; done
  pkill -x xfce4-panel >/dev/null 2>&1 || true
  sleep 0.6
  pkill -x xfconfd >/dev/null 2>&1 || true   # иначе кэш каналов перезапишет наш XML
  sleep 0.8
}

start_panel() {
  if [ -f "$HOME/.config/eww/enabled" ]; then
    "$HOME/.local/bin/eww-topbar" restart
    say "панель Eww запущена"
    return 0
  fi
  setsid -f xfce4-panel >/dev/null 2>&1
  sleep 1.5
  if pgrep -x xfce4-panel >/dev/null; then
    say "панель запущена (pid $(pgrep -x xfce4-panel | head -1))"
  else
    warn "панель не поднялась — запусти вручную: xfce4-panel &"
    return 1
  fi
}

install_launchers() { # массив LAUNCHERS=( "id:путь.desktop" ... ) из manifest.env
  declare -p LAUNCHERS >/dev/null 2>&1 || return 0
  local entry id src base dir
  for entry in "${LAUNCHERS[@]}"; do
    id="${entry%%:*}"; src="${entry#*:}"
    [ -f "$src" ] || { warn "нет .desktop для плагина $id: $src"; continue; }
    base=$(basename "$src")
    dir="$HOME/.config/xfce4/panel/launcher-$id"
    mkdir -p "$dir"
    cp -f "$src" "$dir/$base"
    echo "плагин $id → $base"
  done
}

install_panel_layout() { # каталог профиля
  local pdir="$1" xml="$pdir/xfce4-panel.xml"
  # если профиль подключает dock плагина plank — берём раскладку без нижней панели-дока
  if [ -n "${PLANK_THEME:-}" ] && [ -f "$pdir/xfce4-panel-plank.xml" ] && command -v plank >/dev/null; then
    xml="$pdir/xfce4-panel-plank.xml"
    echo "раскладка панели: только верхняя строка (нижний док отдан plank)"
  fi
  if [ ! -f "$xml" ]; then
    warn "в профиле нет своей раскладки панели — панель не трогаю"
    return 0
  fi
  stop_panel
  cp "$xml" "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
  if [ -d "$pdir/panel" ]; then            # launcher-<id>/ подкаталоги плагина launcher
    mkdir -p "$HOME/.config/xfce4/panel"
    cp -a "$pdir/panel/." "$HOME/.config/xfce4/panel/"
  fi
  install_launchers
  pkill -x xfconfd >/dev/null 2>&1 || true
  sleep 0.6
  start_panel
}

# ── обои ───────────────────────────────────────────────────────────────────────
set_wallpaper() { # абсолютный путь к картинке — ставится на все мониторы и рабочие столы
  local img="$1"
  [ -f "$img" ] || { warn "обои не найдены: $img"; return 1; }
  local props p st prefix ws count i
  props=$(xfconf-query -c xfce4-desktop -l 2>/dev/null | grep -E '/backdrop/.*/last-image$' || true)
  if [ -z "$props" ]; then
    prefix="/backdrop/screen0/monitor0/workspace"
    count=$(xfconf-query -c xfwm4 -p /general/workspace_count 2>/dev/null || echo 1)
    for ((i=0; i<count; i++)); do
      xfconf_set xfce4-desktop "${prefix}${i}/last-image" string "$img"
      xfconf_set xfce4-desktop "${prefix}${i}/image-style" int 5
    done
  else
    while read -r p; do
      [ -n "$p" ] || continue
      prefix="${p%/last-image}"                     # .../monitorXXX/workspaceN
      st="${p%last-image}image-style"
      xfconf_set xfce4-desktop "$p"  string "$img"
      xfconf_set xfce4-desktop "$st" int 5
      prefix="${prefix%/workspace*}"                # .../monitorXXX
      count=$(xfconf-query -c xfwm4 -p /general/workspace_count 2>/dev/null || echo 1)
      for ((i=0; i<count; i++)); do
        local wp="${prefix}/workspace${i}/last-image"
        xfconf_has xfce4-desktop "$wp" || xfconf_set xfce4-desktop "$wp" string "$img"
      done
    done <<< "$props"
  fi
  xfdesktop --reload >/dev/null 2>&1 || true
  echo "обои: $img (все мониторы/рабочие столы)"
}

# ── шрифт (только если реально установлен) ─────────────────────────────────────
font_available() { # без пайпов: pipefail + grep -q даёт SIGPIPE и ложное «нет»
  local fams
  fams=$(fc-list : family 2>/dev/null | tr ',' '\n' || true)
  grep -qix "$1" <<< "$fams"
}

# ── plank (док) ────────────────────────────────────────────────────────────────
plank_setup() { # каталог профиля
  local pdir="$1" tdir="$HOME/.local/share/plank/themes"
  if [ -z "${PLANK_THEME:-}" ]; then
    # в профиле нет дока — гасим plank и убираем автозапуск, чтобы он не висел поверх чужой темы
    pkill -x plank >/dev/null 2>&1 || true
    rm -f "$HOME/.config/autostart/plank.desktop"
    echo "plank: выключен (в профиле нет своей темы дока)"
    return 0
  fi
  if ! command -v plank >/dev/null; then
    warn "plank не установлен — док пропущен. Установка: sudo pacman -S plank"
    return 0
  fi
  mkdir -p "$tdir"
  [ -d "$pdir/plank" ] && cp -a "$pdir/plank/." "$tdir/"
  [ -f "$pdir/autostart/plank.desktop" ] && { mkdir -p "$HOME/.config/autostart"; cp "$pdir/autostart/plank.desktop" "$HOME/.config/autostart/"; }
  local theme="${PLANK_THEME:-WhiteSur-Dark}" path="net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/"
  gsettings set "$path" theme            "'$theme'"                 >/dev/null 2>&1 || true
  gsettings set "$path" position         "'${PLANK_POSITION:-bottom}'" >/dev/null 2>&1 || true
  gsettings set "$path" icon-size        "${PLANK_ICON_SIZE:-44}"    >/dev/null 2>&1 || true
  gsettings set "$path" hide-mode        "'${PLANK_HIDE_MODE:-intelligent}'" >/dev/null 2>&1 || true
  gsettings set "$path" zoom-enabled     true                        >/dev/null 2>&1 || true
  gsettings set "$path" zoom-percent     130                         >/dev/null 2>&1 || true
  if [ -n "${PLANK_ITEMS:-}" ]; then
    local ld="$HOME/.config/plank/dock1/launchers" names=() i=0 app base
    mkdir -p "$ld"; rm -f "$ld"/*.dockitem
    for app in $PLANK_ITEMS; do
      base=$(basename "$app")
      printf '[PlankDockItemPreferences]\nLauncher=file://%s\n' "$app" > "$ld/$(printf '%02d' "$i")-$base.dockitem"
      names+=("$(printf '%02d' "$i")-$base.dockitem")
      i=$((i+1))
    done
    local joined
    joined=$(printf "'%s'," "${names[@]}"); joined="[${joined%,}]"
    gsettings set "$path" dock-items "$joined" >/dev/null 2>&1 || true
  fi
  pkill -x plank >/dev/null 2>&1 || true
  sleep 0.6
  setsid -f plank >/dev/null 2>&1
  echo "plank: тема $theme, док перезапущен"
}

# ── picom (эффекты: скругления, тени, размытие) ───────────────────────────────
picom_setup() { # каталог профиля; включается флагом PICOM_ENABLE=1 в manifest.env
  local pdir="$1"
  local toggle="$DOTFILES_DIR/scripts/picom-toggle.sh"
  if [ "${PICOM_ENABLE:-0}" != "1" ]; then
    pkill -x picom >/dev/null 2>&1 || true
    rm -f "$HOME/.config/autostart/picom.desktop"
    xfconf_set xfwm4 /general/use_compositing bool false  # xfwm4 композитинг выключен
    echo "picom: выключен (в профиле не включён)"
    return 0
  fi
  if [ ! -x "$toggle" ]; then
    warn "нет $toggle — picom пропущен"
    return 0
  fi
  if ! command -v picom >/dev/null && [ ! -x "$HOME/.local/bin/picom" ]; then
    warn "picom не установлен — поставь: sudo pacman -S picom"
  else
    "$toggle" on >/dev/null 2>&1 || warn "picom не поднялся, смотри ~/.cache/picom.log"
  fi
  # автозапуск при входе
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/picom.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=picom
Comment=Композитор: скругления, тени, размытие (Win+P — выключить)
Exec=$toggle on
Icon=video-display
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
  echo "picom: включён (Win+P выключает), автозапуск добавлен"
}

# ── горячие клавиши оформления ────────────────────────────────────────────────
install_keybindings() {
  local toggle="$DOTFILES_DIR/scripts/picom-toggle.sh"
  # Win+P — включить/выключить picom (как просил пользователь)
  xfconf_set xfce4-keyboard-shortcuts "/commands/custom/<Super>p"       string "$toggle"
  # настройки дисплея переезжают с Win+P на Win+Alt+P, чтобы не потерялись
  xfconf_set xfce4-keyboard-shortcuts "/commands/custom/<Super><Alt>p" string "xfce4-display-settings --minimal"
  xfconf_set xfce4-keyboard-shortcuts "/commands/custom/override"      bool   true
  echo "горячие клавиши: Win+P → picom, Win+Alt+P → настройки дисплея"
}

verify_state() {
  say "Проверка"
  printf '  GTK:      %s\n' "$(xfconf-query -c xsettings -p /Net/ThemeName)"
  printf '  иконки:   %s\n' "$(xfconf-query -c xsettings -p /Net/IconThemeName)"
  printf '  курсор:   %s\n' "$(xfconf-query -c xsettings -p /Gtk/CursorThemeName)"
  printf '  окна:     %s\n' "$(xfconf-query -c xfwm4 -p /general/theme)"
  printf '  панель:   %s (pid %s)\n' "$( [ -f "$HOME/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml" ] && echo ok || echo нет)" "$(pgrep -x xfce4-panel | head -1)"
  printf '  обои:     %s\n' "$(xfconf-query -c xfce4-desktop -l | grep -m1 last-image | xargs -r xfconf-query -c xfce4-desktop -p 2>/dev/null)"
}
