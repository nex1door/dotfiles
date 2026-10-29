#!/usr/bin/env bash
# theme-switch.sh — переключение оформления XFCE одной командой, с автобэкапом.
#   ~/dotfiles/scripts/theme-switch.sh list
#   ~/dotfiles/scripts/theme-switch.sh apply macos-bigsur
#   ~/dotfiles/scripts/theme-switch.sh restore-last
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTFILES_DIR="${DOTFILES_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
# shellcheck source=lib-theme.sh
source "$SCRIPT_DIR/lib-theme.sh"
mkdir -p "$STATE_DIR"

usage() {
  cat <<'EOF'
Использование: theme-switch.sh <команда> [аргумент]

  list                             список профилей и бэкапов
  apply <профиль> [--no-backup]    применить профиль (сначала автобэкап текущего)
  import <ссылка> [имя] [флаги]    забрать dotfiles с GitHub и сделать профиль
                                     флаги: --dry-run (только показать),
                                            --exact (сохранить и полный снимок xfconf),
                                            --no-assets (не ставить темы/иконки/шрифты),
                                            --run-installer (разрешить запуск install.sh из репо)
  backup [имя]                     снять бэкап текущего оформления
  restore-last                     вернуть последний автобэкап
  show                             что применено сейчас
  gui                              графическое меню (zenity), «в один клик»
EOF
}

profile_title() { # каталог профиля -> человекочитаемое имя
  local pdir="$1" t=""
  [ -f "$pdir/manifest.env" ] && t=$(grep -m1 '^PROFILE_TITLE=' "$pdir/manifest.env" | cut -d= -f2- | tr -d '"')
  [ -n "$t" ] || t="$(basename "$pdir")"
  printf '%s' "$t"
}

cmd_list() {
  printf 'Профили в %s:\n' "${PROFILES_DIR#$HOME/}"
  local d base
  for d in "$PROFILES_DIR"/*/; do
    [ -d "$d" ] || continue
    base=$(basename "$d")
    printf '  %-28s %s' "$base" "$(profile_title "$d")"
    [ -d "$d/xfconf-xml" ] && printf ' [точный снимок]'
    printf '\n'
  done
  printf '\nСейчас применено: %s\n' "$(cat "$STATE_DIR/current" 2>/dev/null || echo '(неизвестно)')"
}

cmd_backup() {
  local name="${1:-current-$(date '+%Y%m%d_%H%M%S')}"
  local dest="$PROFILES_DIR/$name"
  [ -e "$dest" ] && die "уже существует: $dest"
  mkdir -p "$dest"
  snapshot_state "$dest" >/dev/null
  { echo "# автобэкап оформления, $(date '+%F %T %z')"
    printf 'PROFILE_TITLE=%s\n' "\"Бэкап $(date '+%d.%m.%Y %H:%M')\""
    printf 'PROFILE_DESC=%s\n' "\"Точный снимок xfconf на момент бэкапа\""
  } > "$dest/manifest.env"
  say "бэкап создан: ${dest#$HOME/}"
  ls -1 "$dest" | sed 's/^/  /'
  notify "Бэкап оформления создан" "${dest#$HOME/}"
}

cmd_restore_last() {
  local last
  if [ -s "$STATE_DIR/last-rollback" ]; then
    last=$(cat "$STATE_DIR/last-rollback")
  else
    last=$(ls -1d "$PROFILES_DIR"/_rollback-* 2>/dev/null | sort | tail -1)
  fi
  [ -n "$last" ] && [ -d "$last" ] || die "бэкапов (_rollback-*) не найдено"
  apply_profile "$(basename "$last")" --no-backup
}

install_own_launchers() { # наши собственные ярлыки (переключатель тем) в меню приложений
  mkdir -p "$HOME/.local/share/applications"
  local f
  for f in "$DOTFILES_DIR"/launchers/*.desktop; do
    [ -f "$f" ] || continue
    # в ярлыках путь записан плейсхолдером: подставляем реальный $HOME
    sed "s|@@HOME@@|$HOME|g" "$f" > "$HOME/.local/share/applications/$(basename "$f")"
    chmod 644 "$HOME/.local/share/applications/$(basename "$f")"
  done
  command -v update-desktop-database >/dev/null && \
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
}

apply_profile() {
  local name="$1" flag="${2:-}"
  local pdir="$PROFILES_DIR/$name"
  [ -d "$pdir" ] || die "профиль не найден: $name (смотри: theme-switch.sh list)"

  install_own_launchers

  if [ "$flag" != "--no-backup" ]; then
    local rb="$PROFILES_DIR/_rollback-$(date '+%Y%m%d_%H%M%S')"
    mkdir -p "$rb"
    snapshot_state "$rb" >/dev/null
    printf 'PROFILE_TITLE="Бэкап %s"\n' "$(date '+%d.%m.%Y %H:%M')" > "$rb/manifest.env"
    echo "$rb" > "$STATE_DIR/last-rollback"
    say "текущее оформление сохранено: ${rb#$HOME/}"
  fi

  if [ -d "$pdir/xfconf-xml" ]; then
    say "точное восстановление снимка: $name"
    restore_xml_state "$pdir"
  else
    [ -f "$pdir/manifest.env" ] || die "в профиле нет ни xfconf-xml/, ни manifest.env: $pdir"
    # shellcheck disable=SC1091
    set -a; source "$pdir/manifest.env"; set +a
    say "применяю: ${PROFILE_TITLE:-$name}"
    apply_xfconf_tsv "$pdir/xfconf.tsv"
    install_panel_layout "$pdir"
    apply_xfconf_tsv "$pdir/xfconf.tsv"          # повторно — чтобы кэш xfsettingsd не откатил
    [ -n "${WALLPAPER:-}" ] && set_wallpaper "$WALLPAPER"
    if [ -n "${FONT_NAME:-}" ]; then
      if font_available "${FONT_NAME% *}"; then
        xfconf_set xsettings /Gtk/FontName string "$FONT_NAME"
        echo "шрифт: $FONT_NAME"
      else
        warn "шрифт '${FONT_NAME% *}' не установлен — пропущено"
      fi
    fi
    plank_setup "$pdir"
    picom_setup "$pdir"
    install_keybindings
  fi

  printf '%s\n' "$name" > "$STATE_DIR/current"
  # держим не больше 5 авто-бэкапов, чтобы список профилей не зарастал
  local old
  while read -r old; do
    [ -n "$old" ] && rm -rf "$old"
  done < <(ls -1dt "$PROFILES_DIR"/_rollback-* 2>/dev/null | tail -n +6)
  verify_state
  notify "Оформление применено: ${PROFILE_TITLE:-$name}" "Откат: theme-switch.sh restore-last"
}

cmd_show() {
  verify_state
  printf '  профиль:  %s\n' "$(cat "$STATE_DIR/current" 2>/dev/null || echo '(неизвестно)')"
  printf '  последний автобэкап: %s\n' "$(cat "$STATE_DIR/last-rollback" 2>/dev/null || echo '(нет)')"
}

# ── импорт чужих dotfiles с GitHub ─────────────────────────────────────────────
cmd_import() {
  local url="${1:-}"
  [ -n "$url" ] || die "укажи ссылку: theme-switch.sh import https://github.com/user/repo"
  shift || true

  local name="" flags=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --name)        name="${2:-}"; shift 2 ;;
      --dry-run|--exact|--no-assets|--run-installer) flags+=("$1"); shift ;;
      *)             name="$1"; shift ;;
    esac
  done

  # git@github.com:user/repo.git → https://github.com/user/repo
  case "$url" in
    git@*:*) local host="${url#git@}"; host="${host%%:*}"; local gpath="${url#*:}"
             url="https://${host}/${gpath%.git}" ;;
  esac

  local repo_url="$url" branch="" subdir=""
  case "$url" in
    */tree/*)
      repo_url="${url%%/tree/*}"
      local rest="${url#*/tree/}"
      branch="${rest%%/*}"
      case "$rest" in */*) subdir="${rest#*/}" ;; esac
      ;;
    *.git) repo_url="${url%.git}" ;;
  esac
  [ -n "$repo_url" ] || die "не понял ссылку: $url"

  local base; base=$(basename "$repo_url")
  [ -n "$name" ] || name=$(printf '%s' "$base" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9._-' '-' | sed 's/-\{1,\}/-/g; s/^-//; s/-$//')
  [ -n "$name" ] || name="import-$(date '+%Y%m%d_%H%M%S')"

  local cache="$DOTFILES_DIR/imports/$name"
  if [ -e "$PROFILES_DIR/$name" ] && [ ! -d "$cache/.git" ]; then
    die "профиль '$name' уже есть. Задай другое имя: theme-switch.sh import $url --name другое-имя"
  fi
  mkdir -p "$DOTFILES_DIR/imports"

  if [ -d "$cache/.git" ]; then
    say "обновляю ранее склонированный репозиторий"
    git -C "$cache" pull --ff-only --quiet 2>/dev/null || warn "не удалось обновить клон — беру как есть"
  else
    say "клонирую: $repo_url${branch:+ (ветка $branch)}"
    if [ -n "$branch" ]; then
      git clone --depth=1 --branch "$branch" --quiet "$repo_url" "$cache" || die "не склонировалось: $repo_url"
    else
      git clone --depth=1 --quiet "$repo_url" "$cache" || die "не склонировалось: $repo_url"
    fi
  fi

  local src="$cache"
  [ -n "$subdir" ] && src="$cache/$subdir"
  [ -d "$src" ] || die "в репозитории нет каталога: ${subdir:-/}"

  # ${flags[@]:-} при пустом массиве передаёт пустой аргумент — argparse ругается
  if [ "${#flags[@]}" -gt 0 ]; then
    python3 "$SCRIPT_DIR/import-profile.py" --src "$src" --name "$name" "${flags[@]}"
  else
    python3 "$SCRIPT_DIR/import-profile.py" --src "$src" --name "$name"
  fi
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    say "профиль '$name' доступен в меню «Оформление XFCE» и в: theme-switch.sh list"
    notify "Импортировано: $name" "Можно выбрать в «Оформление XFCE»"
  else
    warn "импорт завершился с кодом $rc (клон остался в ${cache#$HOME/})"
  fi
  return "$rc"
}

case "${1:-}" in
  list)         cmd_list ;;
  apply)        [ -n "${2:-}" ] || die "укажи профиль: theme-switch.sh apply macos-bigsur"; apply_profile "$2" "${3:-}" ;;
  backup)       cmd_backup "${2:-}" ;;
  restore-last) cmd_restore_last ;;
  import)       cmd_import "${@:2}" ;;
  show)         cmd_show ;;
  gui)          exec "$SCRIPT_DIR/theme-menu.sh" ;;
  ""|-h|--help) usage ;;
  *)            warn "неизвестная команда: $1"; usage; exit 2 ;;
esac