#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smart Clipboard — лёгкий менеджер буфера обмена для X11 (XFCE 4.20 / CachyOS).

Один процесс, один файл, без внешних зависимостей кроме PyGObject + GTK3:

  * перехват CLIPBOARD через Gtk.Clipboard "owner-change" (никаких опросов и
    загрузки CPU; бинарные/нетекстовые данные просто игнорируются);
  * полная история в SQLite (~/.local/share/smart-clipboard/history.db):
    текст, длина, sha256-хэш, created_at, last_used_at;
  * дедупликация подряд идущих записей — обновляется только last_used_at;
  * иконка в панели XFCE через StatusNotifierItem (org.kde.StatusNotifierItem)
    + меню через com.canonical.dbusmenu — это то, что умеет systray-плагин
    xfce4-panel 4.20 (старый XEmbed-протокол в нём больше не поддерживается);
  * клик по элементу возвращает текст в CLIPBOARD и PRIMARY;
  * внизу меню: «Очистить видимую историю» и «Выход».

Запуск:
    /usr/bin/python3 smart_clipboard.py             # сервис
    /usr/bin/python3 smart_clipboard.py --self-test # самопроверка без GUI
    /usr/bin/python3 smart_clipboard.py --popup     # показать меню (для хоткея)
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import logging
import os
import re
import signal
import sqlite3
import sys
import time
from pathlib import Path

APP_ID = "smart-clipboard"
APP_TITLE = "Smart Clipboard"

DB_DIR = Path(os.environ.get("SMART_CLIPBOARD_HOME") or (Path.home() / ".local/share" / APP_ID))
DB_PATH = DB_DIR / "history.db"
LOCK_PATH = DB_DIR / "lock"
PID_PATH = DB_DIR / "pid"

#: максимальная длина превью в меню (символы)
PREVIEW_LEN = 52
#: сколько записей показывать в меню по умолчанию
DEFAULT_LIMIT = 25
#: предохранитель от случайных мега-вставок в БД (символы)
MAX_STORED_CHARS = 4_000_000
#: диапазон безопасных int32-идентификаторов для dbusmenu
ID_CLEAR = 2_000_000_001
ID_QUIT = 2_000_000_002
ID_EMPTY = 2_000_000_003
ID_SEPARATOR = 2_000_000_004
ID_HEADER = 2_000_000_005

SNI_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
SNI_IFACE = "org.kde.StatusNotifierItem"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

log = logging.getLogger(APP_ID)


# --------------------------------------------------------------------------- #
#  SQLite-хранилище
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT    NOT NULL,
    length       INTEGER NOT NULL,
    hash         TEXT    NOT NULL,
    created_at   INTEGER NOT NULL,
    last_used_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_hash      ON history(hash);
CREATE INDEX IF NOT EXISTS idx_history_last_used ON history(last_used_at DESC, id DESC);
"""


def content_hash(text: str) -> str:
    """sha256 от UTF-8 представления (surrogatepass — чтобы не падать на битых строках)."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def sanitize(text: str) -> str:
    """Убираем NUL (SQLite их всё равно обрежет) и обрезаем гигантские вставки."""
    if "\x00" in text:
        text = text.replace("\x00", "")
    if len(text) > MAX_STORED_CHARS:
        log.warning("фрагмент %d символов обрезан до %d", len(text), MAX_STORED_CHARS)
        text = text[:MAX_STORED_CHARS]
    return text


def make_preview(text: str, width: int = PREVIEW_LEN) -> str:
    """Однострочное превью: любые пробелы/переносы → один пробел, обрезка по ширине."""
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return "(пробелы)"
    if len(flat) <= width:
        return flat
    return flat[: max(1, width - 1)].rstrip() + "…"


class HistoryDB:
    """Вся работа с SQLite. Один поток (GLib main loop), поэтому connection один."""

    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)

    # -- запись -------------------------------------------------------------
    def add_text(self, text: str, now: int | None = None) -> tuple[str, int] | None:
        """Сохранить фрагмент. Возвращает (kind, id) либо None, если сохранять нечего.

        kind == "new" — новая запись; "dup" — дубликат последней (обновлён last_used_at).
        """
        text = sanitize(text)
        if not text.strip():
            return None
        now = int(time.time()) if now is None else int(now)
        h = content_hash(text)
        last = self.conn.execute(
            "SELECT id, hash FROM history ORDER BY last_used_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if last is not None and last["hash"] == h:
            self.conn.execute("UPDATE history SET last_used_at=? WHERE id=?", (now, last["id"]))
            return "dup", int(last["id"])
        cur = self.conn.execute(
            "INSERT INTO history(content, length, hash, created_at, last_used_at)"
            " VALUES(?,?,?,?,?)",
            (text, len(text), h, now, now),
        )
        return "new", int(cur.lastrowid)

    def touch(self, entry_id: int, now: int | None = None) -> None:
        now = int(time.time()) if now is None else int(now)
        self.conn.execute("UPDATE history SET last_used_at=? WHERE id=?", (now, int(entry_id)))

    def delete_ids(self, ids: list[int]) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        cur = self.conn.execute(f"DELETE FROM history WHERE id IN ({marks})", ids)
        return cur.rowcount or 0

    # -- чтение -------------------------------------------------------------
    def recent(self, limit: int = DEFAULT_LIMIT) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT id, content, length, created_at, last_used_at FROM history"
                " ORDER BY last_used_at DESC, id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        )

    def get(self, entry_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM history WHERE id=?", (int(entry_id),)).fetchone()

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass


# --------------------------------------------------------------------------- #
#  Форматирование меток меню
# --------------------------------------------------------------------------- #
def format_when(ts: int, now: int | None = None) -> str:
    now = int(time.time()) if now is None else int(now)
    lt = time.localtime(ts)
    if time.strftime("%Y-%m-%d", lt) == time.strftime("%Y-%m-%d", time.localtime(now)):
        return time.strftime("%H:%M", lt)
    if now - ts < 2 * 86400:
        return "вчера"
    return time.strftime("%d.%m", lt)


def entry_label(row: sqlite3.Row, show_time: bool = True, width: int = PREVIEW_LEN) -> str:
    text = make_preview(row["content"], width)
    return f"{format_when(row['last_used_at'])}  {text}" if show_time else text


# --- оформление пунктов меню ------------------------------------------------ #
URL_RE = re.compile(r"^(?:https?|ftp|gemini)://\S+$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
CODE_HINTS = (
    "```", "def ", "class ", "function ", "=>", "#include", "#!/", "<?php",
    "SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM", "fn main", "pub fn",
    "import ", "const ", "let ", "sudo ", "pacman -", "systemctl ",
)


def classify(text: str) -> str:
    """Иконка под тип содержимого — чтобы меню читалось глазами, а не только текстом.

    Берём первый вариант, который реально есть в текущей теме иконок.
    """
    stripped = text.strip()
    if URL_RE.match(stripped):
        return _first_available(("applications-internet", "web-browser", "insert-link"))
    if EMAIL_RE.match(stripped):
        return _first_available(("mail-message-new", "mail-unread", "emblem-mail"))
    if any(hint in text for hint in CODE_HINTS):
        return _first_available(("text-x-script", "utilities-terminal", "text-x-generic"))
    return _first_available(("text-x-generic", "text-x-script"))


_ICON_AVAILABLE: dict[str, bool] = {}


def _first_available(candidates: tuple[str, ...]) -> str:
    """Первое имя иконки, которое есть в теме (результат кешируется)."""
    for name in candidates:
        cached = _ICON_AVAILABLE.get(name)
        if cached is None:
            try:
                from gi.repository import Gtk

                cached = Gtk.IconTheme.get_default().has_icon(name)
            except Exception:
                cached = False
            _ICON_AVAILABLE[name] = cached
        if cached:
            return name
    return candidates[0]


def entry_icon(row: sqlite3.Row) -> str:
    return classify(row["content"])


def entry_shortcut(row: sqlite3.Row, show_time: bool = True) -> str:
    """Время уходит в правую колонку (dbusmenu 'shortcut'), а не в текст пункта."""
    return format_when(row["last_used_at"]) if show_time else ""


# --------------------------------------------------------------------------- #
#  Описание интерфейсов D-Bus
# --------------------------------------------------------------------------- #
SNI_XML = f"""
<node>
  <interface name="{SNI_IFACE}">
    <property name="Category"          type="s"      access="read"/>
    <property name="Id"                type="s"      access="read"/>
    <property name="Title"             type="s"      access="read"/>
    <property name="Status"            type="s"      access="read"/>
    <property name="WindowId"          type="i"      access="read"/>
    <property name="IconName"          type="s"      access="read"/>
    <property name="IconPixmap"        type="a(iiay)" access="read"/>
    <property name="OverlayIconName"   type="s"      access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s"      access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName"  type="s"      access="read"/>
    <property name="ToolTip"           type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu"        type="b"      access="read"/>
    <property name="Menu"              type="o"      access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta"       type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>
"""

DBUSMENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg name="parentId"       type="i"  direction="in"/>
      <arg name="recursionDepth" type="i"  direction="in"/>
      <arg name="propertyNames"  type="as" direction="in"/>
      <arg name="revision"       type="u"  direction="out"/>
      <arg name="layout"         type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids"           type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties"    type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id"    type="i" direction="in"/>
      <arg name="name"  type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id"        type="i" direction="in"/>
      <arg name="eventId"   type="s" direction="in"/>
      <arg name="data"      type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events"   type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai"      direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id"         type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids"           type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors"      type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent"   type="i"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id"        type="i"/>
      <arg name="timestamp" type="u"/>
    </signal>
    <property name="Version"        type="u"  access="read"/>
    <property name="TextDirection"  type="s"  access="read"/>
    <property name="Status"         type="s"  access="read"/>
    <property name="IconThemePath"  type="as" access="read"/>
  </interface>
</node>
"""


#: типы dbusmenu-свойств, которые мы отдаём
PROP_TYPES = {
    "label": "s",
    "enabled": "b",
    "visible": "b",
    "type": "s",
    "children-display": "s",
    "icon-name": "s",
    "toggle-type": "s",
    "toggle-state": "i",
}


def prop_variant(name: str, value):
    """Значение свойства dbusmenu → GLib.Variant (у 'shortcut' особый тип aas)."""
    from gi.repository import GLib

    if name == "shortcut":
        if isinstance(value, str):
            value = [value] if value else []
        return GLib.Variant("aas", [[str(part)] for part in (value or [])])
    return GLib.Variant(PROP_TYPES.get(name, "s"), value)


def _node(nid: int, props: dict, children: list) -> "GLib.Variant":
    """Узел dbusmenu: (id, a{sv}, av)."""
    from gi.repository import GLib

    # Внимание: PyGObject не принимает готовый GLib.Variant там, где ожидается
    # a{sv} или av внутри кортежа (KeyError: 0 / "Expected GLib.Variant, but got
    # tuple"), поэтому словарь и список детей передаём как обычные объекты Python.
    props_v = {k: prop_variant(k, v) for k, v in props.items()}
    return GLib.Variant("(ia{sv}av)", (nid, props_v, list(children)))


def menu_model(rows: list, show_time: bool = True, width: int = PREVIEW_LEN):
    """Плоская модель меню: (список пунктов, карта действий {id: (kind, payload)}).

    Пункт — dict с полями id/label/enabled/visible/type/icon-name/shortcut.
    Чистая функция, её проверяет --self-test и ею пользуются обработчики dbusmenu.
    """
    items: list[dict] = []
    actions: dict[int, tuple[str, object]] = {}

    # Шапка: имя приложения слева, счётчик справа (как у «настоящих» меню).
    items.append(
        {
            "id": ID_HEADER,
            "label": f"{APP_TITLE} · {len(rows)}",
            "shortcut": f"{len(rows)} записей" if rows else "пусто",
            "enabled": False,
            "icon-name": ICON_NAME,
            "type": "standard",
        }
    )
    if not rows:
        items.append(
            {
                "id": ID_EMPTY,
                "label": "История пуста",
                "enabled": False,
                "icon-name": "dialog-information",
                "type": "standard",
            }
        )
    for row in rows:
        nid = int(row["id"])
        items.append(
            {
                "id": nid,
                # libdbusmenu-gtk в XFCE не рисует 'shortcut', поэтому время идёт
                # в текст пункта; 'shortcut' оставляем для хостов, которые умеют.
                "label": entry_label(row, show_time, width),
                "shortcut": entry_shortcut(row, show_time),
                "enabled": True,
                "visible": True,
                "icon-name": entry_icon(row),
                "type": "standard",
            }
        )
        actions[nid] = ("entry", nid)

    items.append({"id": ID_SEPARATOR, "type": "separator"})
    items.append(
        {
            "id": ID_CLEAR,
            "label": "Очистить видимую историю",
            "enabled": bool(rows),
            "icon-name": "edit-clear",
            "type": "standard",
        }
    )
    actions[ID_CLEAR] = ("clear", [int(r["id"]) for r in rows])
    items.append(
        {
            "id": ID_QUIT,
            "label": "Выход",
            "enabled": True,
            "icon-name": "application-exit",
            "type": "standard",
        }
    )
    actions[ID_QUIT] = ("quit", None)
    return items, actions


def build_menu_tree(rows: list, show_time: bool = True, width: int = PREVIEW_LEN) -> tuple:
    """Собрать дерево dbusmenu: (root_variant, {id: (kind, payload)})."""
    items, actions = menu_model(rows, show_time, width)
    children = [
        _node(it["id"], {k: v for k, v in it.items() if k != "id"}, []) for it in items
    ]
    root = _node(0, {"children-display": "submenu"}, children)
    return root, actions


# --------------------------------------------------------------------------- #
#  Своя иконка трея (ARGB32 для IconPixmap) — рисуется вручную, без cairo/PIL
# --------------------------------------------------------------------------- #
ICON_SIZES = (16, 20, 22, 24, 32, 48)
_ICO_OUTLINE = (0x2C, 0x32, 0x3A, 255)
_ICO_BODY = (0xF4, 0xF6, 0xFA, 255)
_ICO_ACCENT = (0x35, 0x84, 0xE4, 255)
_ICO_LINE = (0x7E, 0x8A, 0x9E, 255)


def _in_rrect(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render_icon(size: int, ss: int | None = None) -> bytes:
    """Иконка «буфер обмена»: светлый лист, тёмный контур, синий зажим, три строки.

    Возвращает ARGB32 в сетевом порядке байт (A,R,G,B) — формат IconPixmap в SNI.
    Суперсэмплинг даёт сглаженные края без внешних библиотек.
    Мелкие размеры упрощаются (меньше и толще строки), иначе в 16-20 px каша.
    """
    ss = ss or (4 if size <= 24 else 2)
    W = size * ss
    grid = [[(0, 0, 0, 0)] * W for _ in range(W)]

    def rect(x0, y0, x1, y1, radius, color):
        for yy in range(max(0, int(y0 * W)), min(W, int(y1 * W) + 1)):
            fy = yy / W
            row = grid[yy]
            for xx in range(max(0, int(x0 * W)), min(W, int(x1 * W) + 1)):
                if _in_rrect(xx / W, fy, x0, y0, x1, y1, radius):
                    row[xx] = color

    if size <= 20:      # 16-20 px: две толстые строки, крупный зажим
        edge, inset, radius = 0.105, 0.175, 0.18
        clip = (0.300, 0.010, 0.700, 0.200, 0.075, 0.345, 0.045, 0.665, 0.165)
        lines = ((0.430, 0.720, 0.135), (0.655, 0.720, 0.135))
        line_radius = 0.067
    elif size <= 26:    # 22-24 px: три строки средней толщины
        edge, inset, radius = 0.120, 0.180, 0.17
        clip = (0.325, 0.015, 0.675, 0.190, 0.070, 0.360, 0.045, 0.640, 0.160)
        lines = ((0.405, 0.725, 0.100), (0.570, 0.725, 0.100), (0.735, 0.610, 0.100))
        line_radius = 0.050
    else:               # 32+ px: полноценный вариант
        edge, inset, radius = 0.125, 0.185, 0.17
        clip = (0.330, 0.020, 0.670, 0.185, 0.070, 0.365, 0.050, 0.635, 0.155)
        lines = ((0.395, 0.735, 0.080), (0.560, 0.735, 0.080), (0.725, 0.600, 0.080))
        line_radius = 0.040

    rect(edge, 0.095, 1.0 - edge, 0.955, radius, _ICO_OUTLINE)      # корпус, контур
    rect(inset, 0.155, 1.0 - inset, 0.895, radius * 0.65, _ICO_BODY)  # корпус, заливка
    c_x0, c_y0, c_x1, c_y1, c_r, f_x0, f_y0, f_x1, f_y1 = clip
    rect(c_x0, c_y0, c_x1, c_y1, c_r, _ICO_OUTLINE)                 # зажим, контур
    rect(f_x0, f_y0, f_x1, f_y1, c_r * 0.7, _ICO_ACCENT)            # зажим, акцент
    for top, right, height in lines:
        rect(0.255, top, right, top + height, line_radius, _ICO_LINE)

    out = bytearray(size * size * 4)
    n = ss * ss
    for y in range(size):
        for x in range(size):
            sa = sr = sg = sb = 0
            for dy in range(ss):
                row = grid[y * ss + dy]
                for dx in range(ss):
                    pr, pg, pb, pa = row[x * ss + dx]
                    sa += pa
                    sr += pr * pa
                    sg += pg * pa
                    sb += pb * pa
            i = (y * size + x) * 4
            if sa:
                out[i] = sa // n
                out[i + 1] = sr // sa
                out[i + 2] = sg // sa
                out[i + 3] = sb // sa
    return bytes(out)


_ICON_CACHE: list | None = None


def icon_pixmaps() -> list:
    """Кэш готовых иконок: [(w, h, bytes), ...] для свойства IconPixmap."""
    global _ICON_CACHE
    if _ICON_CACHE is None:
        _ICON_CACHE = [(s, s, render_icon(s)) for s in ICON_SIZES]
    return _ICON_CACHE


#: имя нашей иконки в теме (панель XFCE грузит иконку по имени, IconPixmap не рисует)
ICON_NAME = "smart-clipboard"
ICON_THEME_SIZES = (16, 20, 22, 24, 32, 48, 64, 128)
#: hicolor наследуется любой темой иконок, поэтому иконка находится везде
ICON_THEME_DIR = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share")) / "icons/hicolor"


def _png(size: int, argb: bytes) -> bytes:
    """PNG (RGBA) из ARGB32-буфера — свой минимальный энкодер, без PIL."""
    import struct
    import zlib

    rgba = bytearray(size * size * 4)
    for i in range(size * size):
        a, r, g, b = argb[i * 4:i * 4 + 4]
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    raw = b"".join(b"\x00" + bytes(rgba[y * size * 4:(y + 1) * size * 4]) for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def install_icons(base: Path | None = None) -> list[Path]:
    """Положить иконки smart-clipboard в hicolor-тему (~/.local/share/icons).

    Панель XFCE берёт иконку по IconName из темы, поэтому свой рисунок
    устанавливается как обычная тема-иконка, а не как IconPixmap.
    """
    base = Path(base) if base is not None else ICON_THEME_DIR
    written: list[Path] = []
    for size in ICON_THEME_SIZES:
        target = base / f"{size}x{size}" / "apps" / f"{ICON_NAME}.png"
        data = _png(size, render_icon(size))
        if target.exists() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
    return written


def resolve_icon_name(preferred: str = ICON_NAME, fallback: str = "edit-paste") -> str:
    """Имя иконки, которое реально есть в теме."""
    try:
        from gi.repository import Gtk

        theme = Gtk.IconTheme.get_default()
        if theme.has_icon(preferred):
            return preferred
    except Exception:  # pragma: no cover
        pass
    return fallback


# --------------------------------------------------------------------------- #
#  Сервис
# --------------------------------------------------------------------------- #
class ClipboardService:
    def __init__(self, db: HistoryDB, limit: int = DEFAULT_LIMIT, show_time: bool = True,
                 width: int = PREVIEW_LEN, icon_name: str = "edit-paste",
                 icon_mode: str = "both"):
        from gi.repository import Gio, Gtk, Gdk  # noqa: F401  (импорт здесь — для --self-test)

        self.db = db
        self.limit = limit
        self.show_time = show_time
        self.width = width
        self.icon_name = icon_name
        self.icon_mode = icon_mode
        self.revision = 1
        self._gen = 0
        self._conn = None
        self._bus_name = None
        self._registered = False
        self._sni_iface = None
        self._menu_iface = None

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.primary = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
        self.clipboard.connect("owner-change", self._on_owner_change)

    # -- буфер обмена -------------------------------------------------------
    def _on_owner_change(self, clipboard, _event):
        self._gen += 1
        gen = self._gen
        try:
            clipboard.request_text(self._on_clip_text, gen)
        except Exception:
            log.exception("request_text упал")

    def _on_clip_text(self, _clipboard, text, gen):
        if gen != self._gen:
            return  # ответ устарел
        if not text:
            return  # картинка/файл/пустая строка — молча игнорируем
        try:
            result = self.db.add_text(text)
        except Exception:
            log.exception("не удалось записать фрагмент в БД")
            return
        if result is None:
            return
        kind, entry_id = result
        log.debug("%s id=%s len=%s", kind, entry_id, len(text))
        self.notify_history_changed()

    def paste(self, entry_id: int) -> bool:
        row = self.db.get(entry_id)
        if row is None:
            log.warning("запись %s исчезла из БД", entry_id)
            return False
        text = row["content"]
        ok = self.clipboard.set_text(text, -1)
        self.primary.set_text(text, -1)
        self.db.touch(entry_id)
        log.info("возвращено в буфер: id=%s len=%s", entry_id, row["length"])
        self.notify_history_changed()
        return bool(ok)

    # -- уведомления меню ---------------------------------------------------
    def notify_history_changed(self) -> None:
        self.revision = (self.revision + 1) % (2 ** 31)
        if not self._registered:
            return
        try:
            self._emit("com.canonical.dbusmenu", MENU_PATH, "LayoutUpdated",
                       self._variant("(ui)", (self.revision, 0)))
            self._emit(SNI_IFACE, SNI_PATH, "NewToolTip", self._variant("()", ()))
        except Exception:
            log.exception("не удалось отправить сигнал D-Bus")

    def _variant(self, sig: str, value):
        from gi.repository import GLib
        return GLib.Variant(sig, value)

    def _emit(self, iface: str, path: str, name: str, params) -> None:
        if self._conn is None:
            return
        self._conn.emit_signal(None, path, iface, name, params)

    # -- меню (dbusmenu) ----------------------------------------------------
    def _rows(self):
        return self.db.recent(self.limit)

    def _menu_props(self, nid: int) -> dict:
        """Свойства одного пункта (обычные Python-значения) для dbusmenu."""
        if int(nid) == 0:
            return {"children-display": "submenu"}
        items, _actions = menu_model(self._rows(), self.show_time, self.width)
        for it in items:
            if int(it["id"]) == int(nid):
                return {k: v for k, v in it.items() if k != "id"}
        return {}

    def _on_menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        from gi.repository import GLib

        try:
            if method == "GetLayout":
                _parent, _depth, _names = params.unpack()
                root, _actions = build_menu_tree(self._rows(), self.show_time, self.width)
                log.debug("панель запросила меню (revision %d)", self.revision)
                invocation.return_value(
                    GLib.Variant.new_tuple(GLib.Variant("u", self.revision), root)
                )
                return

            if method == "GetGroupProperties":
                ids, _names = params.unpack()
                out = []
                for nid in ids:
                    props = self._menu_props(int(nid))
                    if props:
                        out.append(
                            (int(nid), {k: prop_variant(k, v) for k, v in props.items()})
                        )
                invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
                return

            if method == "GetProperty":
                nid, name = params.unpack()
                props = self._menu_props(int(nid))
                if name in props:
                    variant = prop_variant(name, props[name])
                else:
                    variant = GLib.Variant("s", "")
                invocation.return_value(GLib.Variant("(v)", (variant,)))
                return

            if method == "Event":
                nid, event_id, _data, _ts = params.unpack()
                invocation.return_value(None)
                if event_id == "clicked":
                    GLib.idle_add(self._activate, int(nid))
                return

            if method == "EventGroup":
                events, = params.unpack()
                invocation.return_value(GLib.Variant("(ai)", ([],)))
                for nid, event_id, _data, _ts in events:
                    if event_id == "clicked":
                        GLib.idle_add(self._activate, int(nid))
                return

            if method in ("AboutToShow", "AboutToShowGroup"):
                invocation.return_value(
                    GLib.Variant("(b)", (True,)) if method == "AboutToShow"
                    else GLib.Variant("(aiai)", ([], []))
                )
                self.revision = (self.revision + 1) % (2 ** 31)
                self._emit("com.canonical.dbusmenu", MENU_PATH, "LayoutUpdated",
                           GLib.Variant("(ui)", (self.revision, 0)))
                return

            invocation.return_value(None)
        except Exception:
            log.exception("ошибка обработки %s", method)
            try:
                invocation.return_value(None)
            except Exception:
                pass

    def _on_menu_get(self, _conn, _sender, _path, _iface, name):
        from gi.repository import GLib

        if name == "Version":
            return GLib.Variant("u", 3)
        if name == "TextDirection":
            return GLib.Variant("s", "ltr")
        if name == "Status":
            return GLib.Variant("s", "normal")
        if name == "IconThemePath":
            return GLib.Variant("as", [])
        return None

    def _activate(self, nid: int) -> bool:
        """Действие по клику в меню (пришло от панели через dbusmenu Event)."""
        root, actions = build_menu_tree(self._rows(), self.show_time, self.width)
        kind, payload = actions.get(int(nid), (None, None))
        if kind == "entry":
            self.paste(int(payload))
        elif kind == "clear":
            removed = self.db.delete_ids(list(payload))
            log.info("очищено записей: %s", removed)
            self.notify_history_changed()
        elif kind == "quit":
            log.info("выход по запросу из меню")
            self._quit()
        return False  # однократный idle-callback

    # -- иконка (StatusNotifierItem) ---------------------------------------
    def _on_sni_get(self, _conn, _sender, _path, _iface, name):
        from gi.repository import GLib

        if name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if name == "Id":
            return GLib.Variant("s", APP_ID)
        if name == "Title":
            return GLib.Variant("s", APP_TITLE)
        if name == "Status":
            return GLib.Variant("s", "Active")
        if name == "WindowId":
            return GLib.Variant("i", 0)
        if name == "IconName":
            return GLib.Variant("s", self.icon_name if self.icon_mode in ("theme", "both") else "")
        if name == "IconPixmap":
            if self.icon_mode in ("pixmap", "both"):
                return GLib.Variant("a(iiay)", icon_pixmaps())
            return GLib.Variant("a(iiay)", [])
        if name in ("OverlayIconPixmap", "AttentionIconPixmap"):
            return GLib.Variant("a(iiay)", [])
        if name in ("OverlayIconName", "AttentionIconName", "AttentionMovieName"):
            return GLib.Variant("s", "")
        if name == "ItemIsMenu":
            return GLib.Variant("b", True)
        if name == "Menu":
            return GLib.Variant("o", MENU_PATH)
        if name == "IconThemePath":
            # Хост делает prepend_search_path() — отдаём каталог тем,
            # внутри которого лежит hicolor с нашей иконкой.
            base = ICON_THEME_DIR.parent
            return GLib.Variant("as", [str(base)] if base.exists() else [])
        if name == "ToolTip":
            subtitle = f"{self.db.count()} записей"
            return GLib.Variant("(sa(iiay)ss)", (self.icon_name, [], APP_TITLE, subtitle))
        return None

    def _on_sni_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        invocation.return_value(None)
        if method == "Activate":
            self.show_gtk_menu()

    # -- регистрация на шине ------------------------------------------------
    def start(self) -> None:
        from gi.repository import Gio, GLib

        self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._sni_iface = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        self._menu_iface = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML).interfaces[0]

        self._conn.register_object(SNI_PATH, self._sni_iface, self._on_sni_call, self._on_sni_get, None)
        self._conn.register_object(MENU_PATH, self._menu_iface, self._on_menu_call, self._on_menu_get, None)

        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        Gio.bus_own_name_on_connection(
            self._conn, self._bus_name, Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired, self._on_name_lost,
        )

    def _on_name_acquired(self, connection, name) -> None:
        from gi.repository import Gio, GLib

        self._registered = True
        try:
            connection.call_sync(
                WATCHER_NAME, WATCHER_PATH, WATCHER_NAME, "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (name,)), None, Gio.DBusCallFlags.NONE, 3000, None,
            )
            log.info("StatusNotifierItem зарегистрирован как %s", name)
        except Exception as exc:
            log.warning("RegisterStatusNotifierItem не удался (%s) — иконки в панели не будет, "
                        "но история и хоткей --popup работают", exc)

    def _on_name_lost(self, _connection, name) -> None:
        log.error("не удалось занять имя D-Bus %s — сервис уже запущен?", name)
        self._registered = False

    # -- резервное GTK-меню (хоткей / нет SNI) ------------------------------
    def show_gtk_menu(self) -> bool:
        from gi.repository import Gtk

        def with_icon(item, icon_name):
            """GTK3: иконка в пункте меню — через set_image + always_show_image."""
            try:
                item.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
                item.set_always_show_image(True)
            except Exception:
                pass
            return item

        rows = self._rows()
        menu = Gtk.Menu()
        header = with_icon(Gtk.MenuItem(label=f"{APP_TITLE} · {len(rows)} записей"), "edit-paste")
        header.set_sensitive(False)
        menu.append(header)
        for row in rows:
            item = with_icon(Gtk.MenuItem(label=make_preview(row["content"], self.width)),
                             entry_icon(row))
            item.connect("activate", self._paste_from_gtk, int(row["id"]))
            menu.append(item)
        if not rows:
            empty = with_icon(Gtk.MenuItem(label="История пуста"), "dialog-information")
            empty.set_sensitive(False)
            menu.append(empty)
        menu.append(Gtk.SeparatorMenuItem())
        clear = with_icon(Gtk.MenuItem(label="Очистить видимую историю"), "edit-clear")
        clear.connect("activate", lambda _w: (self.db.delete_ids([int(r["id"]) for r in rows]),
                                              self.notify_history_changed()))
        menu.append(clear)
        quit_item = with_icon(Gtk.MenuItem(label="Выход"), "application-exit")
        quit_item.connect("activate", lambda _w: self._quit())
        menu.append(quit_item)
        menu.show_all()
        try:
            menu.popup_at_pointer(None)
        except Exception:
            log.exception("не удалось показать GTK-меню")
            return False
        return False  # для GLib.idle_add

    def _paste_from_gtk(self, _widget, entry_id: int) -> None:
        self.paste(entry_id)

    # -- выход --------------------------------------------------------------
    def _quit(self) -> bool:
        from gi.repository import Gtk

        Gtk.main_quit()
        return False

    def stop(self) -> None:
        self.db.close()


# --------------------------------------------------------------------------- #
#  Запуск
# --------------------------------------------------------------------------- #
def acquire_single_instance() -> bool:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_PATH), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    # fd не закрываем до выхода — блокировка держится на открытом дескрипторе
    globals()["_LOCK_FD"] = fd
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return True


def run_service(args) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib

    if not Gtk.init_check()[0]:
        log.error("не удалось подключиться к X11 (DISPLAY=%r)", os.environ.get("DISPLAY"))
        return 2
    if not acquire_single_instance():
        log.info("экземпляр уже запущен (pid %s)", PID_PATH.read_text().strip() if PID_PATH.exists() else "?")
        return 0

    # Своя иконка: кладём PNG в отдельную тему и отдаём её панели через
    # IconThemePath — так рисунок не зависит от темы оформления и от кэша панели.
    try:
        written = install_icons()
        if written:
            log.info("иконки установлены: %d файлов в %s", len(written), ICON_THEME_DIR)
    except Exception:
        log.exception("не удалось установить иконки в тему")
    icon_name = args.icon_name
    if icon_name == ICON_NAME:
        icon_name = resolve_icon_name()

    db = HistoryDB(Path(args.db) if args.db else DB_PATH)
    service = ClipboardService(db, limit=args.limit, show_time=not args.no_time,
                               width=args.width, icon_name=icon_name,
                               icon_mode=args.icon_mode)
    service.start()
    service.notify_history_changed()

    def _sig(_signum, _frame=None):
        GLib.idle_add(lambda: (Gtk.main_quit(), False)[1])
        return True

    # GLib.unix_signal_add помечен deprecated — берём GLibUnix, если он есть.
    try:
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ImportError, ValueError):  # pragma: no cover - старые glib
        signal_add = GLib.unix_signal_add

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal_add(GLib.PRIORITY_DEFAULT, sig, _sig, sig)
    if hasattr(signal, "SIGUSR1"):
        signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1,
                   lambda: (service.show_gtk_menu(), False)[1])

    # первый запуск: подхватить то, что уже лежит в буфере
    try:
        current = service.clipboard.wait_for_text()
        if current:
            db.add_text(current)
    except Exception:
        log.exception("не удалось прочитать буфер при старте")

    log.info("сервис запущен: БД %s, записей %d, лимит меню %d",
             db.path, db.count(), args.limit)
    try:
        Gtk.main()
    finally:
        service.stop()
        try:
            LOCK_PATH.unlink()
            PID_PATH.unlink()
        except OSError:
            pass
        log.info("сервис остановлен")
    return 0


def show_popup() -> int:
    """--popup: попросить уже запущенный сервис показать меню (для хоткея)."""
    if not PID_PATH.exists():
        print("smart-clipboard не запущен", file=sys.stderr)
        return 1
    pid = int(PID_PATH.read_text().strip())
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError as exc:
        print(f"не удалось отправить SIGUSR1 процессу {pid}: {exc}", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
#  Самопроверка (без GUI)
# --------------------------------------------------------------------------- #
def self_test() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        print(f"{'ok  ' if cond else 'FAIL'}  {name}{(' — ' + extra) if extra and not cond else ''}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDB(Path(tmp) / "history.db")
        t0 = 1_700_000_000

        check("новая запись добавляется", db.add_text("hello", t0) == ("new", 1))
        check("подряд идущий дубликат не плодит строк", db.add_text("hello", t0 + 5) == ("dup", 1))
        check("в БД одна строка", db.count() == 1, str(db.count()))
        check("last_used_at обновился",
              db.conn.execute("SELECT last_used_at FROM history WHERE id=1").fetchone()[0] == t0 + 5)

        db.add_text("world", t0 + 10)
        check("другая запись добавляется", db.count() == 2)
        db.add_text("hello", t0 + 15)
        check("дубликат не подряд → новая строка", db.count() == 3)

        rows = db.recent(2)
        check("recent сортирует по last_used_at", rows[0]["content"] == "hello" and rows[1]["content"] == "world",
              f"{[r['content'] for r in rows]}")

        db.touch(2, t0 + 100)
        check("touch поднимает запись наверх", db.recent(1)[0]["content"] == "world")

        check("пустые строки игнорируются", db.add_text("   \n\t ", t0 + 200) is None)
        db.add_text("a\x00b", t0 + 201)
        check("NUL вычищается", db.recent(1)[0]["content"] == "ab")

        n = db.count()
        check("delete_ids удаляет только указанные", db.delete_ids([1, 2]) == 2 and db.count() == n - 2)

        # превью
        check("переносы схлопываются",
              make_preview("line1\n\nline2\r\n\tline3") == "line1 line2 line3",
              make_preview("line1\n\nline2\r\n\tline3"))
        check("длинный текст обрезается до 56",
              len(make_preview("x" * 500)) == PREVIEW_LEN and make_preview("x" * 500).endswith("…"))
        check("кириллица не рвётся", make_preview("Привет мир") == "Привет мир")
        check("пробельная строка даёт заглушку", make_preview("   ") == "(пробелы)")

        # модель и дерево меню
        rows = db.recent(DEFAULT_LIMIT)
        items, actions = menu_model(rows)
        check("в меню шапка + N записей + разделитель + 2 кнопки",
              len(items) == len(rows) + 4, f"{len(items)} vs {len(rows) + 4}")
        ids = [int(it["id"]) for it in items]
        check("id пунктов уникальны", len(ids) == len(set(ids)))
        check("все id в диапазоне int32", all(0 < i < 2 ** 31 - 1 for i in ids))
        check("шапка первая и неактивна",
              items[0]["id"] == ID_HEADER and items[0]["enabled"] is False)
        check("в шапке счётчик записей",
              items[0]["shortcut"] == f"{len(rows)} записей", items[0]["shortcut"])
        check("в шапке видно количество", items[0]["label"].endswith(f"· {len(rows)}"), items[0]["label"])
        check("метка пункта = время + превью",
              items[1]["label"] == entry_label(rows[0], True))
        check("shortcut заполнен временем (для хостов, которые его рисуют)",
              items[1]["shortcut"] == format_when(rows[0]["last_used_at"]), items[1]["shortcut"])
        check("у пунктов есть иконки типов",
              all(it.get("icon-name") for it in items[1:1 + len(rows)]))
        check("иконки кнопок заданы",
              items[-2].get("icon-name") == "edit-clear" and items[-1].get("icon-name") == "application-exit")
        check("действия clear/quit зарегистрированы",
              actions.get(ID_CLEAR, ("",))[0] == "clear" and actions.get(ID_QUIT, ("",))[0] == "quit")
        check("clear знает id видимых записей",
              actions[ID_CLEAR][1] == [int(r["id"]) for r in rows])
        check("разделитель — separator", items[-3]["type"] == "separator")

        root, _act = build_menu_tree(rows)
        rid, _props, kids = root.unpack()
        check("корень меню = id 0", rid == 0)
        check("дерево собралось целиком", len(kids) == len(items))
        check("метка пункта — строка GVariant",
              isinstance(kids[0][1]["label"], str) and kids[0][1]["label"] == items[0]["label"])

        empty_items, _empty_actions = menu_model([])
        check("пустая история даёт пункт-заглушку", empty_items[1]["id"] == ID_EMPTY)
        check("при пустой истории clear выключен", empty_items[-2]["enabled"] is False)

        # оформление: классификация содержимого и иконка трея
        check("URL → иконка глобуса", classify("https://example.com/a?b=1") == "applications-internet")
        check("почта → mail-message-new", classify("user@example.com") == "mail-message-new")
        check("код → text-x-script", classify("SELECT * FROM history;") == "text-x-script")
        check("обычный текст → text-x-generic", classify("просто строка") == "text-x-generic")
        for size in (16, 24, 48):
            data = render_icon(size)
            opaque = sum(1 for i in range(3, len(data), 4) if data[i] > 128)
            check(f"иконка {size}px: ARGB и не пустая",
                  len(data) == size * size * 4 and opaque > size * size * 0.2,
                  f"{opaque} непрозрачных пикселей")

        # иконка в теме: PNG-энкодер без PIL и установка в собственный каталог
        png = _png(16, render_icon(16))
        check("PNG с корректной сигнатурой", png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 200)
        written = install_icons(Path(tmp) / "icons")
        check("установлены все размеры иконки",
              len(written) == len(ICON_THEME_SIZES), f"{len(written)}")
        check("файлы легли в <size>x<size>/apps",
              all((Path(tmp) / "icons" / f"{s}x{s}" / "apps" / f"{ICON_NAME}.png").exists()
                  for s in ICON_THEME_SIZES))
        check("повторная установка ничего не пишет", install_icons(Path(tmp) / "icons") == [])

        db.close()

    print()
    print(f"Провалено проверок: {len(failures)}" if failures else "Все проверки пройдены.")
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Smart Clipboard — менеджер буфера обмена для X11")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="сколько элементов в меню (по умолчанию %(default)s)")
    parser.add_argument("--width", type=int, default=PREVIEW_LEN, help="ширина превью в символах (по умолчанию %(default)s)")
    parser.add_argument("--no-time", action="store_true", help="не показывать время в превью")
    parser.add_argument("--icon-name", default=ICON_NAME,
                        help="имя иконки из темы (по умолчанию %(default)s)")
    parser.add_argument("--icon-mode", default="both", choices=("theme", "pixmap", "both"),
                        help="иконка трея: тема, своя векторная или обе (по умолчанию %(default)s)")
    parser.add_argument("--db", help="путь к базе (по умолчанию %s)" % DB_PATH)
    parser.add_argument("--self-test", action="store_true", help="прогнать самопроверку без GUI")
    parser.add_argument("--popup", action="store_true", help="показать меню у курсора (для хоткея)")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.self_test:
        return self_test()
    if args.popup:
        return show_popup()
    return run_service(args)


if __name__ == "__main__":
    sys.exit(main())