#!/usr/bin/env bash
# theme-menu.sh — графический переключатель оформления XFCE (zenity), «в один клик».
# Запускается из меню приложений или кнопкой на панели.
#
# ВАЖНО (проверено на zenity 4.2.2): zenity --list НЕ разбивает строки на столбцы
# по '|', поэтому список одностолбцовый: «Название  [ключ_профиля]».
# Действия распознаются по префиксу, ключ — по квадратным скобкам в конце строки.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTFILES_DIR="${DOTFILES_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
# shellcheck source=lib-theme.sh
source "$SCRIPT_DIR/lib-theme.sh"

command -v zenity >/dev/null || die "zenity не установлен (pacman -S zenity)"
[ -d "$PROFILES_DIR" ] || die "нет каталога профилей: $PROFILES_DIR"

ACTION_BACKUP="Сделать бэкап текущего оформления"
ACTION_RESTORE="Вернуть последний бэкап"
ACTION_IMPORT="Импортировать тему из GitHub"

rows=("⏪  $ACTION_BACKUP")
last=$(ls -1d "$PROFILES_DIR"/_rollback-* 2>/dev/null | sort | tail -1 || true)
[ -n "${last:-}" ] && rows+=("↩  $ACTION_RESTORE")
rows+=("⬇  $ACTION_IMPORT")

for d in "$PROFILES_DIR"/*/; do
  [ -d "$d" ] || continue
  base=$(basename "$d")
  case "$base" in _rollback-*) continue ;; esac
  title=$(grep -m1 '^PROFILE_TITLE=' "$d/manifest.env" 2>/dev/null | cut -d= -f2- | tr -d '"')
  [ -n "$title" ] || title="$base"
  rows+=("$title  [$base]")
done

# точечные автобэкапы — в конец списка
for d in "$PROFILES_DIR"/_rollback-*/; do
  [ -d "$d" ] || continue
  base=$(basename "$d")
  rows+=("$(printf '%s' "$base" | sed 's/^_rollback-/Бэкап /')  [$base]")
done

current=$(cat "$STATE_DIR/current" 2>/dev/null || echo "неизвестно")

rows_file=$(mktemp "${TMPDIR:-/tmp}/theme-rows.XXXXXX")
# уникальные строки: zenity ругается «Duplicate item» и выбирает наугад при повторах
printf '%s\n' "${rows[@]}" | awk '!seen[$0]++' > "$rows_file"

choice=$(zenity --list --title="Оформление XFCE" \
       --text="<b>Сейчас применено:</b> $current" \
       --column="Тема или действие" --print-column=1 \
       --width=760 --height=480 \
       --ok-label="Применить" --cancel-label="Отмена" < "$rows_file") || { rm -f "$rows_file"; exit 0; }
rm -f "$rows_file"
[ -n "${choice:-}" ] || exit 0

log=$(mktemp "${TMPDIR:-/tmp}/theme-menu.XXXXXX.log")

case "$choice" in
  *"$ACTION_BACKUP")
    notify "Сохраняю текущее оформление" "несколько секунд"
    "$SCRIPT_DIR/theme-switch.sh" backup >>"$log" 2>&1
    ;;
  *"$ACTION_RESTORE")
    notify "Возвращаю последний бэкап" "несколько секунд"
    "$SCRIPT_DIR/theme-switch.sh" restore-last >>"$log" 2>&1
    ;;
  *"$ACTION_IMPORT")
    url=$(zenity --entry --title="Импорт темы из GitHub" \
          --text="Ссылка на репозиторий с dotfiles или темой XFCE:" \
          --entry-text="https://github.com/" --width=620) || url=""
    if [ -n "${url:-}" ]; then
      notify "Импортирую тему" "$url"
      "$SCRIPT_DIR/theme-switch.sh" import "$url" >>"$log" 2>&1
    fi
    ;;
  *"["*"]")
    key="${choice##*[}"
    key="${key%]*}"
    [ -n "$key" ] || key="$choice"
    notify "Применяю: $key" "панель перезапустится автоматически"
    "$SCRIPT_DIR/theme-switch.sh" apply "$key" >>"$log" 2>&1
    ;;
  *)
    "$SCRIPT_DIR/theme-switch.sh" apply "$choice" >>"$log" 2>&1
    ;;
esac
rc=$?

zenity --text-info --title="Результат (код $rc)" --filename="$log" \
       --width=780 --height=480 --ok-label="Закрыть" || true
[ "$rc" -eq 0 ] || zenity --error --text="Что-то пошло не так, смотри вывод выше." --width=420 || true
rm -f "$log"