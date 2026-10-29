#!/usr/bin/env python3
"""WhiteSur Eww: desktop events, launchers, media and transient popups."""
import ctypes
import datetime
import json
import locale
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time

import gi
gi.require_version('Gio', '2.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GioUnix', '2.0')
from gi.repository import Gio, GioUnix, GLib, Gtk

ROOT = Path.home() / '.config/eww'
EWW = str(Path.home() / '.local/bin/eww')
SCRIPT = str(ROOT / 'scripts/bridge.py')
STATE = Path.home() / '.local/state/eww-topbar'
POPUPS = ('apps', 'audio', 'calendar', 'session')


def run(*args, check=False):
    return subprocess.run(args, capture_output=True, text=True, timeout=4, check=check).stdout.strip()


def eww(*args):
    return run(EWW, '--config', str(ROOT), *args)


def detached(*args, external=False):
    if external:
        # GUI applications must outlive the panel, especially the theme switcher
        # which deliberately stops/restarts Eww while applying a profile.
        args = ('systemd-run', '--user', '--collect', '--quiet',
                '--unit=eww-action-' + str(time.time_ns()),
                '--service-type=exec', '--property=ExitType=cgroup', '--', *args)
    log = (STATE / 'actions.log').open('a')
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    log.close()


def bus_call(connection, name, path, interface, method, parameters=None):
    return connection.call_sync(name, path, interface, method, parameters, None,
                                Gio.DBusCallFlags.NONE, 700, None).unpack()


def players(connection):
    names = bus_call(connection, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus', 'ListNames')[0]
    found = []
    for name in names:
        if not name.startswith('org.mpris.MediaPlayer2.'):
            continue
        try:
            props = bus_call(connection, name, '/org/mpris/MediaPlayer2',
                'org.freedesktop.DBus.Properties', 'GetAll',
                GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',)))[0]
            found.append((name, props))
        except GLib.Error:
            pass
    return sorted(found, key=lambda x: x[1].get('PlaybackStatus') != 'Playing')


def close_popups():
    # A generation token lets older guards exit without closing newer popups.
    (STATE / 'popup-token').write_text('closed')
    active = [line.split(':')[0].strip() for line in eww('active-windows').splitlines()]
    opened = [name for name in POPUPS if name in active]
    if opened:
        eww('close', *opened)


class X11:
    def __init__(self):
        self.x = ctypes.CDLL('libX11.so.6')
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.d = self.x.XOpenDisplay(None)
        if not self.d:
            raise RuntimeError('X11 display is unavailable')
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.root = self.x.XDefaultRootWindow(self.d)
        self.x.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_void_p] * 7
        self.x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.escape = self.x.XKeysymToKeycode(self.d, 0xff1b)

    def pointer(self):
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        self.x.XQueryPointer(self.d, self.root, ctypes.byref(root), ctypes.byref(child),
                            ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
        return rx.value, ry.value, mask.value

    def escaped(self):
        keys = (ctypes.c_ubyte * 32)()
        self.x.XQueryKeymap(self.d, keys)
        return bool(keys[self.escape // 8] & (1 << (self.escape % 8)))


def popup_rect(name):
    # GDK tracks actual geometry, including monitor changes and WM placement.
    import gi
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gdk, GdkX11
    prop = run('xprop', '-root', '_NET_CLIENT_LIST')
    display = Gdk.Display.get_default()
    for wid in re.findall(r'0x[0-9a-fA-F]+', prop):
        props = run('xprop', '-id', wid, 'WM_NAME')
        if f'"Eww - {name}"' not in props:
            continue
        window = GdkX11.X11Window.foreign_new_for_display(display, int(wid, 16))
        if window:
            rect = window.get_frame_extents()
            return rect.x, rect.y, rect.width, rect.height
    return None


def guard(name, token):
    time.sleep(0.05)
    x = X11()
    previous = x.pointer()[2]
    while (STATE / 'popup-token').read_text() == token:
        px, py, mask = x.pointer()
        pressed = (mask & 0x700) and not (previous & 0x700)
        outside = False
        if pressed and py > 52:
            rect = popup_rect(name)
            outside = bool(rect and not (rect[0] <= px < rect[0] + rect[2] and
                                        rect[1] <= py < rect[1] + rect[3]))
        if x.escaped() or outside:
            close_popups()
            return
        previous = mask
        time.sleep(0.06)


def toggle(name):
    if name not in POPUPS:
        raise ValueError(name)
    active = eww('active-windows')
    was_open = any(line.split(':')[0].strip() == name for line in active.splitlines())
    close_popups()
    if was_open:
        return
    if name == 'apps':
        generate_apps()
    eww('open', name)
    token = str(time.time_ns())
    (STATE / 'popup-token').write_text(token)
    detached(sys.executable, SCRIPT, 'guard', name, token)


def icon_path(info):
    icon = info.get_icon()
    if icon:
        found = Gtk.IconTheme.get_default().lookup_by_gicon(icon, 32, Gtk.IconLookupFlags.FORCE_SIZE)
        if found:
            return found.get_filename()
    fallback = Gtk.IconTheme.get_default().lookup_icon('application-x-executable', 32, 0)
    return fallback.get_filename() if fallback else ''


def generate_apps():
    original = json.loads((STATE / 'initial-state.json').read_text())['xfce4-panel']
    menu_path = STATE / 'menu-state.json'
    if menu_path.exists():
        menu = json.loads(menu_path.read_text())
    else:
        menu = {kind: [x['value'] for x in original.get('/plugins/plugin-1/' + kind, {}).get('values', [])]
                for kind in ('favorites', 'recent')}
        menu_path.write_text(json.dumps(menu, ensure_ascii=False))
    # Keep the user's Whisker favorites and recent applications in the same order.
    def ids(kind):
        return menu[kind]
    def button(app_id):
        app = GioUnix.DesktopAppInfo.new(app_id)
        if not app:
            return None
        q = lambda value: json.dumps(value, ensure_ascii=False)
        command = shlex.join([SCRIPT, 'launch-app', app_id])
        return ('(button :class "app-row" :hexpand true :tooltip ' + q(app.get_display_name()) +
                ' :onclick ' + q(command) + ' :timeout "10s" (box :space-evenly false :spacing 9 ' +
                '(image :path ' + q(icon_path(app)) + ' :image-width 24 :image-height 24) ' +
                '(label :xalign 0 :limit-width 20 :text ' + q(app.get_display_name()) + ')))')
    def widget(name, entries):
        items = [b for app_id in entries if (b := button(app_id))]
        rows = []
        for i in range(0, len(items), 2):
            row = items[i:i + 2]
            if len(row) == 1:
                row.append('(box)')
            rows.append('(box :space-evenly true :spacing 5 ' + ' '.join(row) + ')')
        return f'(defwidget {name} [] (box :orientation "v" :space-evenly false :spacing 2 ' + ' '.join(rows) + '))'
    # Five recent rows retain every item from the old menu without a long scroll.
    text = widget('favorite-apps', ids('favorites')) + '\n' + widget('recent-apps', ids('recent')) + '\n'
    path = ROOT / 'generated.yuck'
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def listen():
    locale.setlocale(locale.LC_TIME, '')
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    state = dict(time='', date='', full_date='', volume=0, muted=False,
                 volume_icon='󰕾', sink='', title='Рабочий стол',
                 media='Нет воспроизведения', playing=False)
    last_output = ['']
    children = []
    def emit():
        output = json.dumps(state, ensure_ascii=False)
        if output != last_output[0]:
            print(output, flush=True)
            last_output[0] = output
    def audio():
        try:
            default = run('pactl', 'get-default-sink')
            sinks = json.loads(run('pactl', '-f', 'json', 'list', 'sinks'))
            sink = next((s for s in sinks if s['name'] == default), None)
            if sink:
                values = [int(v['value_percent'].strip('%')) for v in sink['volume'].values()]
                state['volume'] = round(sum(values) / len(values)) if values else 0
                state['muted'] = sink['mute']
                state['sink'] = sink.get('description', default)
                state['volume_icon'] = '󰝟' if state['muted'] else ('󰕿' if state['volume'] < 35 else '󰖀' if state['volume'] < 70 else '󰕾')
        except (ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f'audio: {exc}', file=sys.stderr)
        emit()
        return False
    def media():
        try:
            available = players(connection)
            if available:
                _, p = available[0]
                m = p.get('Metadata', {})
                title = m.get('xesam:title', 'Медиаплеер')
                artist = ', '.join(m.get('xesam:artist', []))
                state['media'] = f'{artist} — {title}' if artist else title
                state['playing'] = p.get('PlaybackStatus') == 'Playing'
            else:
                state.update(media='Нет воспроизведения', playing=False)
        except GLib.Error:
            pass
        emit()
        return True
    def tick():
        now = datetime.datetime.now()
        state.update(time=now.strftime('%H:%M'), date=now.strftime('%a, %d %b'),
                     full_date=now.strftime('%A, %d %B %Y'))
        # Titles are data only: never interpolate window or media text into shell commands.
        try:
            active = run('xprop', '-root', '_NET_ACTIVE_WINDOW').split()[-1]
            if active not in ('0x0', '0x00000000'):
                title = run('xprop', '-id', active, '_NET_WM_NAME')
                if ' = ' in title:
                    title = title.split(' = ', 1)[1].strip('"').replace('\\"', '"')
                    if not title.startswith('Eww - '):
                        state['title'] = title[:180]
            else:
                state['title'] = 'Рабочий стол'
        except subprocess.SubprocessError:
            pass
        emit()
        return True
    pending_audio = [0]
    def pulse_event(channel, condition):
        line = channel.readline()
        if not line:
            return False
        if (' on sink ' in line or ' on server ' in line) and not pending_audio[0]:
            def update():
                pending_audio[0] = 0
                return audio()
            pending_audio[0] = GLib.timeout_add(80, update)
        return True
    proc = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, text=True,
                            env={**os.environ, 'LC_ALL': 'C'})
    children.append(proc)
    GLib.io_add_watch(proc.stdout, GLib.IO_IN | GLib.IO_HUP, pulse_event)
    connection.signal_subscribe(None, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
        '/org/mpris/MediaPlayer2', None, Gio.DBusSignalFlags.NONE,
        lambda *_: media())
    tick(); audio(); media()
    GLib.timeout_add_seconds(2, tick)
    GLib.timeout_add_seconds(5, media)
    loop = GLib.MainLoop()
    def finish(*_):
        for child in children:
            child.terminate()
        loop.quit()
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    try:
        loop.run()
    except BrokenPipeError:
        finish()


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    command = sys.argv[1]
    args = sys.argv[2:]
    if command == 'listen':
        listen()
    elif command == 'generate':
        generate_apps()
    elif command == 'toggle':
        toggle(args[0])
    elif command == 'guard':
        guard(args[0], args[1])
    elif command == 'close':
        close_popups()
    elif command == 'launch-app':
        app = GioUnix.DesktopAppInfo.new(args[0])
        if app:
            close_popups()
            detached('gio', 'launch', app.get_filename(), external=True)
            menu_path = STATE / 'menu-state.json'
            menu = json.loads(menu_path.read_text())
            menu['recent'] = ([args[0]] + [item for item in menu['recent'] if item != args[0]])[:10]
            menu_path.write_text(json.dumps(menu, ensure_ascii=False))
    elif command == 'wallpaper':
        close_popups()
        detached(str(Path.home() / 'WallpaperEngine/launch.sh'), external=True)
    elif command == 'theme':
        close_popups()
        detached(str(Path.home() / 'dotfiles/scripts/theme-menu.sh'), external=True)
    elif command == 'mixer':
        close_popups(); detached('pavucontrol', external=True)
    elif command == 'appfinder':
        close_popups(); detached('xfce4-appfinder', external=True)
    elif command == 'lock':
        close_popups(); detached('xflock4', external=True)
    elif command == 'logout':
        close_popups(); detached('xfce4-session-logout', external=True)
    elif command == 'switch-user':
        close_popups(); detached('xfce4-session-logout', '--switch-user', external=True)
    elif command == 'mute':
        run('pactl', 'set-sink-mute', '@DEFAULT_SINK@', 'toggle')
    elif command == 'set-volume':
        volume = max(0, min(150, round(float(args[0]))))
        run('pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{volume}%')
    elif command == 'volume-scroll':
        step = '+3%' if args[0] == 'up' else '-3%'
        current = run('pactl', 'get-sink-volume', '@DEFAULT_SINK@')
        match = re.search(r'(\d+)%', current)
        volume = int(match[1]) if match else 50
        target = max(0, min(150, volume + (3 if step == '+3%' else -3)))
        run('pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{target}%')
    elif command == 'media':
        if args[0] not in ('Previous', 'PlayPause', 'Next'):
            return
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        available = players(connection)
        if available:
            bus_call(connection, available[0][0], '/org/mpris/MediaPlayer2',
                     'org.mpris.MediaPlayer2.Player', args[0])
    else:
        raise ValueError(f'Unknown action: {command}')


if __name__ == '__main__':
    main()
