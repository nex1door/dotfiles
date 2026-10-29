#!/usr/bin/env bash
# install-assets.sh — установка/пересборка ассетов macOS-темы БЕЗ root.
# Ставит: WhiteSur GTK (+xfwm4) в ~/.themes, WhiteSur иконки и курсоры в ~/.local/share/icons,
#          шрифт Inter, обои, иконку Apple-меню. Всё в $HOME, sudo не нужен.
# Нужны только: git, curl, node/npm (для dart-sass), python3.
# Повторный запуск безопасен (пересобирает и перезаписывает).
set -uo pipefail

BUILD_DIR="$HOME/dotfiles/.build"
THEMES_DIR="$HOME/.themes"
ICONS_DIR="$HOME/.local/share/icons"
FONTS_DIR="$HOME/.local/share/fonts"
WALL_DIR="$HOME/Изображения/Обои/macos"
NPM_PREFIX="$HOME/.local/share/npm-global"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*" >&2; }
need() { command -v "$1" >/dev/null || { warn "нужна команда: $1"; return 1; }; }

mkdir -p "$BUILD_DIR" "$HOME/.local/bin"

# ── 1. sassc-совместимый shim поверх dart-sass (sassc в системе нет) ───────────
say "1/6 sassc → dart-sass"
if ! command -v sassc >/dev/null || ! sassc --version >/dev/null 2>&1; then
  if [ ! -x "$NPM_PREFIX/bin/sass" ]; then
    need npm || exit 1
    mkdir -p "$NPM_PREFIX"
    npm i -g --prefix "$NPM_PREFIX" sass || { warn "не удалось поставить dart-sass"; exit 1; }
  fi
  cat > "$HOME/.local/bin/sassc" <<'SHIM'
#!/usr/bin/env bash
# sassc-совместимый shim: переводит вызовы sassc (libsass) на dart-sass.
set -euo pipefail
SASS_BIN="${SASS_BIN:-$HOME/.local/share/npm-global/bin/sass}"
[ -x "$SASS_BIN" ] || { echo "sassc-shim: dart-sass не найден: $SASS_BIN" >&2; exit 127; }
opts=(--no-source-map --quiet-deps); pos=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    -t|--style) opts+=("--style=$2"); shift 2 ;;
    -s)         opts+=("--style=compressed"); shift ;;
    -I|--load-path) opts+=("--load-path=$2"); shift 2 ;;
    -p)         shift 2 ;;
    -m|--sourcemap|-a|--precision|-C|--omit-map-comment|-M) shift ;;
    --) shift; while [ "$#" -gt 0 ]; do pos+=("$1"); shift; done ;;
    *)  pos+=("$1"); shift ;;
  esac
done
exec "$SASS_BIN" "${opts[@]}" "${pos[@]}"
SHIM
  chmod +x "$HOME/.local/bin/sassc"
fi
export PATH="$HOME/.local/bin:$PATH"
echo "sassc: $(command -v sassc)"

# ── 2. исходники тем ──────────────────────────────────────────────────────────
say "2/6 исходникиWhiteSur"
clone() { # url каталог
  local url="$1" dir="$BUILD_DIR/$2"
  [ -d "$dir/.git" ] && { echo "уже склонирован: $2"; return 0; }
  git clone --depth=1 -q "$url" "$dir" && echo "склонирован: $2"
}
clone https://github.com/vinceliuice/WhiteSur-gtk-theme.git  gtk
clone https://github.com/vinceliuice/WhiteSur-icon-theme.git icons
clone https://github.com/vinceliuice/WhiteSur-cursors.git    cursors
[ -d "$BUILD_DIR/smallsur/.git" ] || git clone --depth=1 -q https://github.com/jothi-prasath/SmallSur.git "$BUILD_DIR/smallsur"

# ── 3. GTK + xfwm4 тема ───────────────────────────────────────────────────────
say "3/6 WhiteSur GTK/xfwm4 → $THEMES_DIR"
( cd "$BUILD_DIR/gtk" && SHELL_VERSION=48 PATH="$HOME/.local/bin:$PATH" \
  ./install.sh -c dark -c light -o normal -d "$THEMES_DIR" ) || warn "сборка GTK-темы упала"
ls -d "$THEMES_DIR"/WhiteSur-* 2>/dev/null

# ── 4. иконки и курсоры ───────────────────────────────────────────────────────
say "4/6 иконки и курсоры → $ICONS_DIR"
( cd "$BUILD_DIR/icons" && ./install.sh -d "$ICONS_DIR" ) || warn "иконки не установились"
( cd "$BUILD_DIR/cursors" && ./install.sh ) || warn "курсоры не установились"
# XFCE (xfsettingsd) ищет тему курсора в ~/.icons и /usr/share/icons, а не в ~/.local/share/icons —
# без этой ссылки xfsettingsd откатывает курсор на имя темы иконок.
mkdir -p "$HOME/.icons"
ln -sfn "$ICONS_DIR/WhiteSur-cursors" "$HOME/.icons/WhiteSur-cursors"
echo "ссылка для курсора: ~/.icons/WhiteSur-cursors"

# ── 5. шрифт Inter (открытая замена SF Pro) ───────────────────────────────────
say "5/6 шрифт Inter"
if fc-list : family 2>/dev/null | tr ',' '\n' | grep -qix Inter; then
  echo "Inter уже установлен"
else
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/inter.XXXXXX")
  url=$(curl -s --max-time 25 https://api.github.com/repos/rsms/inter/releases/latest |
        grep -oP '"browser_download_url":\s*"\K[^"]+Inter-[\d.]+\.zip' | head -1)
  if [ -n "$url" ]; then
    curl -sL --max-time 300 -o "$tmp/inter.zip" "$url" &&
      mkdir -p "$FONTS_DIR/Inter" &&
      unzip -oq "$tmp/inter.zip" -d "$tmp" &&
      find "$tmp" -name 'Inter*.otf' -o -name 'Inter*.ttf' | while read -r f; do cp "$f" "$FONTS_DIR/Inter/"; done
    fc-cache -f "$FONTS_DIR" >/dev/null 2>&1 || true
    echo "Inter: $(fc-list : family | grep -cix inter) файл(ов) видно системе"
  else
    warn "не нашёл ссылку на Inter — шрифт пропущен (тема применится со старым шрифтом)"
  fi
  rm -rf "$tmp"
fi

# ── 6. обои и иконка Apple-меню ───────────────────────────────────────────────
say "6/6 обои и иконка Apple-меню"
mkdir -p "$WALL_DIR"
cp -f "$BUILD_DIR"/smallsur/wallpaper/* "$WALL_DIR/" 2>/dev/null || true
ls -1 "$WALL_DIR" | sed 's/^/  /'

mkdir -p "$ICONS_DIR/hicolor/scalable/apps"
if [ ! -s "$ICONS_DIR/hicolor/scalable/apps/apple-menu.svg" ]; then
  curl -sL --max-time 20 -o /tmp/apple.svg \
    "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/apple.svg" &&
  python3 - "$ICONS_DIR/hicolor/scalable/apps/apple-menu.svg" <<'PY'
import pathlib, re, sys
src = pathlib.Path("/tmp/apple.svg").read_text()
src = src.replace('width="24"', 'width="128"').replace('height="24"', 'height="128"')
# simple-icons отдаёт path БЕЗ fill → на тёмной панели логотип был бы чёрным.
# Ставим светлый fill явно.
if 'fill=' in src:
    src = re.sub(r'fill="[^"]*"', 'fill="#f2f2f2"', src, count=1)
else:
    src = src.replace('<path ', '<path fill="#f2f2f2" ', 1)
pathlib.Path(sys.argv[1]).write_text(src)
print("apple-menu.svg записан (светлый fill)")
PY
fi

cat <<'EOF'

Готово. Ассеты на месте:
  ~/.themes/WhiteSur-Dark (и Light)      GTK + xfwm4
  ~/.local/share/icons/WhiteSur-dark     иконки
  ~/.local/share/icons/WhiteSur-cursors  курсоры
  ~/.local/share/fonts/Inter             шрифт (если скачался)

Опционально (нужен sudo, ставит пользователь):
  sudo pacman -S plank                 # настоящий док с зумом и скруглением
  sudo pacman -S appmenu-gtk-module xfce4-appmenu-plugin   # глобальное меню в верхней строке
  # альтернатива shim-у, если хочется системный sassc:
  sudo pacman -S sassc
EOF