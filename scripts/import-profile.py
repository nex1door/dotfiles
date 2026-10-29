#!/usr/bin/env python3
"""import-profile.py — превращает чужие dotfiles с GitHub в профиль «Оформление XFCE».

Разбирает склонированный репозиторий, находит в нём всё, что относится к оформлению XFCE:
  * XML каналов xfconf (xfce-perchannel-xml/*.xml, <channel name="...">) — темы, шрифт, обои, панель
  * настройки окна (xfwm4: тема, раскладка кнопок, центрирование заголовка)
  * панель: xfce4-panel.xml целиком
  * ассеты: GTK-темы (~/.themes), темы иконок, курсоры, шрифты, обои, темы дока plank
и собирает профиль: manifest.env + xfconf.tsv + xfce4-panel.xml + plank/ + обои.

Ассеты устанавливаются сразу в домашние каталоги (темы, иконки, курсоры, шрифты) — они
не дублируются внутри профиля. Скрипты установки из репозитория НЕ запускаются:
о них печатается предупреждение с готовой командой (запуск только по флагу --run-installer).

Использование:
  import-profile.py --src DIR --name ИМЯ [--dry-run] [--exact] [--run-installer] [--no-assets]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HOME = Path.home()
THEMES_DIR = HOME / ".themes"
ICONS_DIR = HOME / ".local" / "share" / "icons"
OLD_ICONS_DIR = HOME / ".icons"
FONTS_DIR = HOME / ".local" / "share" / "fonts"
WALL_DIR = HOME / "Изображения" / "Обои"
PROFILES_DIR = HOME / "dotfiles" / "profiles"

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
BUILD_MARKERS = ("meson.build", "Makefile", "CMakeLists.txt", "Cargo.toml", "package.json")
INSTALLER_NAMES = ("install.sh", "setup.sh", "install", "build.sh", "install-arch.sh", "install-debian.sh")
IGNORE_DIRS = {".git", ".github", "node_modules", "__pycache__", "docs", "screenshots", "img", "images-preview"}

report: list[str] = []
warnings: list[str] = []


def say(line: str = "") -> None:
    report.append(line)


def warn(line: str) -> None:
    warnings.append(line)


def size_mb(p: Path) -> float:
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / (1024 * 1024)
    except OSError:
        return 0.0


def walk_dirs(root: Path):
    for cur, dirs, _files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        yield Path(cur)


# ── xfconf ─────────────────────────────────────────────────────────────────────
def parse_channel_xml(path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Возвращает {канал: [(свойство, тип, значение), ...]} — только листовые свойства."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return out
    root = tree.getroot()
    if root.tag != "channel":
        return out
    chan = root.get("name") or path.stem
    props: list[tuple[str, str, str]] = []

    def walk(node: ET.Element, prefix: str) -> None:
        for prop in node.findall("property"):
            name = prop.get("name")
            if name is None:
                continue
            ptype = prop.get("type") or "string"
            value = prop.get("value")
            children = prop.findall("property")
            here = f"{prefix}/{name}"
            if children:
                walk(prop, here)
            elif ptype == "array":
                vals = [v.get("value") for v in prop.findall("value") if v.get("value") is not None]
                if vals:
                    props.append((here, "string", vals[-1]))
            elif value is not None:
                props.append((here, ptype, value))

    walk(root, "")
    if props:
        out[chan] = props
    return out


def find_channels(src: Path) -> dict[str, Path]:
    """Ищет xml-файлы каналов xfconf в любом месте дерева."""
    found: dict[str, Path] = {}
    for path in src.rglob("*.xml"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        try:
            head = path.read_text(errors="ignore")[:400]
        except OSError:
            continue
        if "<channel" not in head:
            continue
        for chan in parse_channel_xml(path):
            found.setdefault(chan, path)
    return found


def prop(channels: dict[str, dict], chan: str, name: str) -> str | None:
    for p, _t, v in channels.get(chan, {}).get("props", []):  # type: ignore[index]
        if p == name:
            return v
    return None


# ── ассеты ─────────────────────────────────────────────────────────────────────
SKIP_NAME_MARKERS = ("template", "example", "sample", "skeleton", "placeholder", "_src", "src-")


def looks_like_gtk_theme(d: Path) -> bool:
    """Тема GTK/xfwm4: каталог с gtk-2.0/gtk-3.0/xfwm4. index.theme НЕ обязателен —
    XFCE показывает темы из ~/.themes по наличию подкаталогов, а не по index.theme."""
    name = d.name.lower()
    if not name or any(m in name for m in SKIP_NAME_MARKERS):
        return False
    return any((d / sub).is_dir() for sub in ("gtk-2.0", "gtk-3.0", "gtk-4.0", "xfwm4", "metacity-1", "cinnamon"))


def looks_like_icon_theme(d: Path, idir: Path) -> bool:
    if d == idir or not (d / "index.theme").exists():
        return False
    return any((d / sub).is_dir() for sub in ("apps", "places", "actions", "status", "mimetypes", "categories", "devices"))


def looks_like_cursor_theme(d: Path) -> bool:
    return (d / "cursors").is_dir() and ((d / "cursor.theme").exists() or (d / "index.theme").exists())


def looks_like_plank_theme(d: Path) -> bool:
    return (d / "dock.theme").exists()


def looks_like_wallpaper_dir(d: Path) -> bool:
    name = d.name.lower()
    rigid = any(k in name for k in ("wallpaper", "background", "обои", "скриншоты"))
    return rigid and any(f.suffix.lower() in IMG_EXT for f in d.iterdir() if f.is_file())


def collect_assets(src: Path) -> dict[str, list[Path]]:
    res: dict[str, list[Path]] = {"gtk": [], "icons": [], "cursors": [], "fonts": [], "wallpapers": [], "plank": []}
    seen: set[Path] = set()
    for d in walk_dirs(src):
        if d in seen:
            continue
        try:
            if looks_like_gtk_theme(d) and d not in res["gtk"]:
                res["gtk"].append(d)
                seen.add(d)
        except OSError:
            pass
        idir = src
        try:
            if looks_like_icon_theme(d, idir):
                res["icons"].append(d)
        except OSError:
            pass
        if looks_like_cursor_theme(d):
            res["cursors"].append(d)
        if looks_like_plank_theme(d):
            res["plank"].append(d)
    # курсоры, которые лежат готовым каталогом ~/.icons, а не под index.theme
    for d in walk_dirs(src):
        if (d / "cursors").is_dir() and (d / "cursor.theme").exists():
            res["cursors"].append(d)
    for f in src.rglob("*"):
        if f.suffix.lower() in (".ttf", ".otf") and f.is_file():
            res["fonts"].append(f)
        elif f.is_file() and f.suffix.lower() in IMG_EXT and f.stat().st_size > 300_000:
            if any(k in f.parent.name.lower() for k in ("wallpaper", "background", "обои")):
                res["wallpapers"].append(f)
    # уникализируем и упорядочиваем: сначала настоящие темы (в theme/themes/.themes, с xfwm4)
    for k in res:
        res[k] = sorted(set(res[k]))
    if res["gtk"]:
        res["gtk"].sort(key=lambda p: (
            0 if p.parent.name in ("theme", "themes", ".themes") else 1,
            0 if (p / "xfwm4").is_dir() else 1,
            len(p.name),
        ))
    # «россыпь» картинок-иконок (icons/ico, icons/png и т.п.) — это не тема, ставить нечего
    loose_icons = [d for d in walk_dirs(src)
                   if d.name in ("ico", "png", "svg", "icons-extra") and not (d / "index.theme").exists()
                   and any(f.suffix.lower() in (".png", ".svg", ".ico") for f in d.iterdir() if f.is_file())]
    res["loose_icons"] = sorted(loose_icons)  # type: ignore[assignment]
    return res


def find_installers(src: Path) -> list[Path]:
    out = []
    for f in src.rglob("*"):
        if f.is_file() and f.name in INSTALLER_NAMES and not any(p in IGNORE_DIRS for p in f.parts):
            out.append(f)
    return sorted(set(out))


def find_build_markers(src: Path) -> list[Path]:
    return sorted({f for f in src.rglob("*") if f.name in BUILD_MARKERS and f.is_file()})


# ── установка ассетов ──────────────────────────────────────────────────────────
def install_asset(kind: str, path: Path, dry: bool) -> str:
    if kind == "gtk":
        dest = THEMES_DIR / path.name
    elif kind == "icons":
        dest = ICONS_DIR / path.name
    elif kind == "cursors":
        dest = ICONS_DIR / path.name
    elif kind == "plank":
        dest = HOME / ".local" / "share" / "plank" / "themes" / path.name
    elif kind == "fonts":
        dest = FONTS_DIR / path.name
    else:
        raise ValueError(kind)
    tag = "  → "
    if dry:
        return f"{tag}{dest} (не копирую, пробный прогон)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    if path.is_dir():
        shutil.copytree(path, dest, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(path, dest)
    if kind == "cursors":  # xfsettingsd ищет курсоры только в ~/.icons
        OLD_ICONS_DIR.mkdir(parents=True, exist_ok=True)
        link = OLD_ICONS_DIR / path.name
        if link.is_symlink() or link.exists():
            try:
                link.unlink() if link.is_symlink() else shutil.rmtree(link)
            except OSError:
                pass
        link.symlink_to(dest)
    return f"{tag}{dest}"


# ── сборка профиля ─────────────────────────────────────────────────────────────
def build_profile(src: Path, name: str, dry: bool, exact: bool, run_installer: bool, no_assets: bool) -> int:
    pdir = PROFILES_DIR / name
    say(f"репозиторий: {src}")
    say(f"профиль:     {pdir}")

    channels: dict[str, dict] = {}
    for chan, path in find_channels(src).items():
        props = parse_channel_xml(path)
        channels[chan] = {"file": path, "props": props.get(chan, [])}
    say(f"найдено каналов xfconf: {len(channels)}" + (f" — {', '.join(sorted(channels))}" if channels else ""))

    assets = collect_assets(src)
    for kind in ("gtk", "icons", "cursors", "fonts", "wallpapers", "plank"):
        if assets.get(kind):
            say(f"найдено {kind}: {len(assets[kind])}")
    if assets.get("loose_icons"):
        say(f"найдены россыпи картинок-иконок (не темы, пропущены): "
            + ", ".join(str(d.relative_to(src)) for d in assets["loose_icons"][:4]))

    installers = find_installers(src)
    builders = find_build_markers(src)

    # ── ключи для xfconf.tsv ──
    keys: list[tuple[str, str, str, str]] = []

    def add(chan: str, p: str, default_type: str = "string", value: str | None = None) -> None:
        v = value if value is not None else prop(channels, chan, p)
        if v is None:
            return
        ptype = default_type
        for pp, tt, vv in channels.get(chan, {}).get("props", []):
            if pp == p:
                ptype = tt
        if any(k[0] == chan and k[1] == p for k in keys):
            return
        keys.append((chan, p, ptype, v))

    add("xsettings", "/Net/ThemeName")
    add("xsettings", "/Net/IconThemeName")
    add("xsettings", "/Gtk/CursorThemeName")
    add("xsettings", "/Gtk/CursorThemeSize", "int")
    add("xsettings", "/Gtk/FontName")
    add("xsettings", "/Gtk/DecorationLayout")
    add("xfwm4", "/general/theme")
    add("xfwm4", "/general/button_layout")
    add("xfwm4", "/general/title_alignment")
    add("xfwm4", "/general/use_compositing", "bool")
    add("xfwm4", "/general/frame_opacity", "int")

    gtk_theme = next((k[3] for k in keys if k[:2] == ("xsettings", "/Net/ThemeName")), None)
    icon_theme = next((k[3] for k in keys if k[:2] == ("xsettings", "/Net/IconThemeName")), None)
    cursor_theme = next((k[3] for k in keys if k[:2] == ("xsettings", "/Gtk/CursorThemeName")), None)
    font_name = next((k[3] for k in keys if k[:2] == ("xsettings", "/Gtk/FontName")), None)
    xfwm_theme = next((k[3] for k in keys if k[:2] == ("xfwm4", "/general/theme")), None)

    # если в репозитории нет xfconf, но есть темы — берём имена папок
    if not gtk_theme and assets["gtk"]:
        gtk_theme = assets["gtk"][0].name
        keys.append(("xsettings", "/Net/ThemeName", "string", gtk_theme))
        warn(f"имя GTK-темы взято из каталога: {gtk_theme}")
    if not icon_theme and assets["icons"]:
        icon_theme = assets["icons"][0].name
        keys.append(("xsettings", "/Net/IconThemeName", "string", icon_theme))
    if not cursor_theme and assets["cursors"]:
        cursor_theme = assets["cursors"][0].name
        keys.append(("xsettings", "/Gtk/CursorThemeName", "string", cursor_theme))
    if not xfwm_theme and gtk_theme:
        # проверяем и в источнике, и в уже установленной теме
        src_theme = next((p for p in assets["gtk"] if p.name == gtk_theme), None)
        has_xfwm = (src_theme is not None and (src_theme / "xfwm4").is_dir()) or \
                   (THEMES_DIR / gtk_theme / "xfwm4").is_dir()
        if has_xfwm:
            xfwm_theme = gtk_theme
            keys.append(("xfwm4", "/general/theme", "string", xfwm_theme))

    wallpaper = None
    for p, _t, v in channels.get("xfce4-desktop", {}).get("props", []):
        if p.endswith("last-image") and v:
            wallpaper = v
            break
    # обои из чужого конфига часто указывают на файл с их машины: оставляем только существующие
    if wallpaper and not Path(wallpaper).exists():
        cand = next((f for f in assets["wallpapers"]), None)
        if cand is not None:
            wallpaper = str(WALL_DIR / name / cand.name)
        else:
            warn(f"в чужом конфиге обои {wallpaper} — такого файла нет, ключ пропущен")
            wallpaper = None

    panel_src = None
    if "xfce4-panel" in channels:
        cand = Path(channels["xfce4-panel"]["file"])
        text = cand.read_text(errors="ignore")
        if "<property name=\"panels\"" in text:
            panel_src = cand

    plank_theme = assets["plank"][0].name if assets["plank"] else None

    if not keys and not panel_src and not any(assets.values()):
        warn("в репозитории не нашлось ни настроек XFCE, ни тем/иконок/обоев — импортировать нечего")
        for line in report + ["", "предупреждения:"] + [f"  ! {w}" for w in warnings]:
            print(line)
        return 2

    # ── итоговые файлы профиля ──
    if not dry:
        pdir.mkdir(parents=True, exist_ok=True)

    if keys:
        tsv = ["# импортировано из " + str(src), "# канал:::свойство:::тип:::значение"]
        tsv += [f"{c}:::{p}:::{t}:::{v}" for c, p, t, v in keys]
        if not dry:
            (pdir / "xfconf.tsv").write_text("\n".join(tsv) + "\n")
        say(f"xfconf.tsv: {len(keys)} ключей")

    if panel_src:
        if not dry:
            shutil.copy2(panel_src, pdir / "xfce4-panel.xml")
        say(f"панель: взята из {panel_src.relative_to(src)}")

    if plank_theme and not no_assets:
        for d in assets["plank"]:
            if not dry:
                dest = pdir / "plank" / d.name
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copytree(d, dest, dirs_exist_ok=True)
        say(f"темы дока plank: {', '.join(d.name for d in assets['plank'])}")

    if assets["wallpapers"] and not no_assets:
        wdir = WALL_DIR / name
        if not dry:
            wdir.mkdir(parents=True, exist_ok=True)
            for f in assets["wallpapers"][:12]:
                shutil.copy2(f, wdir / f.name)
            if wallpaper is None and assets["wallpapers"]:
                wallpaper = str(wdir / assets["wallpapers"][0].name)
        say(f"обои: {len(assets['wallpapers'][:12])} → {wdir}")

    # ── установка ассетов в домашние каталоги ──
    if not no_assets:
        for kind in ("gtk", "icons", "cursors", "plank", "fonts"):
            for a in assets[kind][:20]:
                if kind == "fonts" and a.stat().st_size < 1000:
                    continue
                say(f"{kind}: {a.name}" + install_asset(kind, a, dry))

    # ── manifest.env ──
    # проверяем, что упомянутые темы реально есть в системе: часто в репозитории только конфиг
    def theme_available(kind: str, nm: str | None) -> bool:
        if not nm:
            return True
        paths = {
            "gtk": (THEMES_DIR, Path("/usr/share/themes")),
            "icons": (ICONS_DIR, Path("/usr/share/icons")),
            "cursors": (OLD_ICONS_DIR, ICONS_DIR, Path("/usr/share/icons")),
        }[kind]
        return any((p / nm).is_dir() for p in paths)

    already_warned: set[str] = set()
    for kind, nm in (("gtk", gtk_theme), ("gtk", xfwm_theme), ("icons", icon_theme), ("cursors", cursor_theme)):
        if nm and not theme_available(kind, nm) and nm not in already_warned:
            already_warned.add(nm)
            warn(f"темы «{nm}» нет в системе, и репозиторий её не принёс — останется прежняя "
                 f"({'оформление окон' if kind == 'gtk' else 'иконки' if kind == 'icons' else 'курсор'})")

    title = name.replace("-", " ").replace("_", " ").strip().title()
    desc_bits = [b for b in (gtk_theme, icon_theme, cursor_theme) if b]
    manifest = [
        f"# Импортировано из {src}",
        f'PROFILE_TITLE="{title}"',
        f'PROFILE_DESC="Импорт с GitHub: {", ".join(desc_bits) if desc_bits else "оформление из репозитория"}"',
        "",
        f"GTK_THEME={gtk_theme or ''}",
        f"XFWM_THEME={xfwm_theme or ''}",
        f"ICON_THEME={icon_theme or ''}",
        f"CURSOR_THEME={cursor_theme or ''}",
    ]
    if font_name:
        manifest.append(f'FONT_NAME="{font_name}"')
    if wallpaper:
        manifest.append(f'WALLPAPER="{wallpaper}"')
    if plank_theme:
        manifest += ["", f'PLANK_THEME="{plank_theme}"', 'PLANK_POSITION="bottom"', "PLANK_ICON_SIZE=44",
                     'PLANK_HIDE_MODE="intelligent"']
    if not dry:
        (pdir / "manifest.env").write_text("\n".join(manifest) + "\n")

    if exact and channels:
        xdir = pdir / "xfconf-xml"
        if not dry:
            xdir.mkdir(parents=True, exist_ok=True)
            for chan, meta in channels.items():
                shutil.copy2(meta["file"], xdir / f"{chan}.xml")
        say(f"точный снимок: {len(channels)} каналов в xfconf-xml/")

    # ── сборка из исходников / чужие установщики ──
    if installers:
        warn("в репозитории есть скрипты установки — я их НЕ запускаю:")
        for i in installers[:5]:
            warn(f"  {i.relative_to(src)}")
        if run_installer:
            for i in installers[:1]:
                say(f"запускаю по флагу --run-installer: {i.relative_to(src)}")
                if not dry:
                    subprocess.run(["bash", str(i)], cwd=str(i.parent), check=False)
        else:
            warn(f"  запустить осознанно: bash {installers[0]}")
    if builders and not installers and not assets["gtk"]:
        warn("похоже, это исходники темы, а не готовый набор (есть "
             + ", ".join(b.name for b in builders[:3]) + ") — тему надо собрать их сборочным скриптом")

    say("")
    say(f"Готово: профиль «{title}» [{name}] добавлен в список.")
    say(f"Применить: ~/dotfiles/scripts/theme-switch.sh apply {name}")
    for line in report:
        print(line)
    if warnings:
        print("\nпредупреждения:")
        for w in warnings:
            print(f"  ! {w}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Импорт dotfiles с GitHub в профиль оформления XFCE")
    ap.add_argument("--src", required=True, help="каталог со склонированным репозиторием")
    ap.add_argument("--name", required=True, help="имя профиля (латиница, дефисы)")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    ap.add_argument("--exact", action="store_true", help="сохранить также точный снимок xfconf-xml")
    ap.add_argument("--run-installer", action="store_true", help="разрешить запуск install.sh из репозитория")
    ap.add_argument("--no-assets", action="store_true", help="не устанавливать темы/иконки/шрифты, только конфиг")
    a = ap.parse_args()
    src = Path(a.src).expanduser().resolve()
    if not src.is_dir():
        print(f"нет каталога: {src}", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,48}", a.name):
        print("имя профиля: только латиница, цифры, точка, дефис, подчёркивание (до 48 символов)", file=sys.stderr)
        return 1
    return build_profile(src, a.name, a.dry_run, a.exact, a.run_installer, a.no_assets)


if __name__ == "__main__":
    sys.exit(main())