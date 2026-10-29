# Верхняя панель Eww: виджеты, действия, трей

Панель — это [Eww](https://github.com/elkowar/eww) (сборка из официального репозитория,
коммит `48f5aa8b…`, X11). Она **не заменяет** `xfce4-panel` навсегда: `~/.config/eww/enabled`
— флаг, по которому переключатель тем понимает, что панель сейчас Eww, а не XFCE.
`eww-topbar restore` возвращает штатную панель.

Файлы:

| Файл | Роль |
|---|---|
| `config/eww/eww.yuck` | состав панели и выпадающих окон |
| `config/eww/eww.scss` | цвета, скругления, размеры («тёмное стекло») |
| `config/eww/generated.yuck` | избранные и недавние приложения (генерируется) |
| `config/eww/scripts/bridge.py` | состояние рабочего стола и все действия кнопок |
| `config/eww/scripts/restore-shortcuts.py` | аккуратный откат добавленных хоткеев |
| `config/eww/assets/apple.svg`, `wallhaven.svg` | иконки кнопок |
| `local/bin/eww-topbar` | управление панелью (start/restart/stop/restore/status) |
| `config/systemd/user/eww-topbar.service`, `eww-tray-bridge.service` | запуск и восстановление |

## eww.yuck — что видно

`(deflisten desktop ...)` подписывается на `bridge.py listen`: одна JSON-строка состояния
(время, дата, громкость, mute, иконка громкости, имя выхода, заголовок активного окна,
медиа, playing). Eww перерисовывает только изменившиеся поля.

Окно `topbar`: `:monitor 0`, геометрия `x=0 y=8 width=99.3% height=40`, `:stacking "bg"`,
`:windowtype "dock"`, `wm-ignore false`, `struts top = 56px` (панель резервирует место,
окна не заезжают под неё). Внутри `centerbox`:

* слева — кнопка Apple (`toggle apps`, тултип «избранное и недавние»), разделитель,
  кнопка Wallhaven (запуск движка обоев), разделитель, заголовок активного окна;
* центр — часы: дата + время, клик открывает календарь с номерами недель;
* справа — `systray`, громкость (клик — попап звука, колесо — ±3 %, правая кнопка — mute),
  кнопка оформления (запускает `theme-menu.sh`), кнопка питания (попап сеанса).

Попапы: `calendar` (340×360), `audio` (360×290, шкала 0–150 %, карточка «сейчас играет»
с Previous/PlayPause/Next и кнопкой «Открыть микшер»), `apps` (470×550, поиск, избранное,
недавние), `session` (300×260: блокировка, смена пользователя, диалог выхода).

`eww.scss` — переменные `$text`, `$muted`, `$accent`, `all: unset` для всего, шрифт Inter 12 px,
иконки — Nerd Font 18 px. Панель: `rgba(20,23,30,0.84)`, рамка 1 px `rgba(220,231,255,0.13)`,
радиус 13. Попапы: радиус 17, фон `rgba(24,28,37,0.96)`, тень не рисуется — её даёт picom
(правила `name = 'Eww - topbar'` и `name *= 'Eww - '`).

## bridge.py — по функциям

`run(*args)` — `subprocess.run` с `capture_output`, `text`, таймаутом 4 с, возвращает stdout
без пробелов по краям. Все внешние команды идут через него.

`eww(*args)` — вызов eww с `--config ~/.config/eww`.

`detached(*args, external=False)` — запуск «в сторону», не блокируя панель. Для GUI-приложений
(`external=True`) оборачивает команду в `systemd-run --user --collect --unit=eww-action-<ns>
--service-type=exec --property=ExitType=cgroup`: приложение переживает перезапуск панели
(переключатель тем специально гасит Eww при применении профиля). Лог — `~/.local/state/eww-topbar/actions.log`.

`bus_call(connection, name, path, interface, method, parameters)` — синхронный вызов D-Bus
через Gio, таймаут 700 мс.

`players(connection)` — список MPRIS-плееров (`org.mpris.MediaPlayer2.*`): для каждого
`GetAll` свойств `Player`, сортировка так, чтобы играющий был первым.

`close_popups()` — пишет в `~/.local/state/eww-topbar/popup-token` строку `closed` (токен
поколения: старые guard-процессы увидят чужой токен и выйдут, не закрыв новый попап) и
закрывает все открытые окна из списка `apps/audio/calendar/session`.

`class X11` — тонкая обёртка над `libX11.so.6` через `ctypes`: `XOpenDisplay`,
`XDefaultRootWindow`, `XQueryPointer` (позиция курсора и маска кнопок), `XQueryKeymap`
(состояние клавиш). `pointer()` возвращает `(x, y, mask)`; `escaped()` — нажат ли Escape
(keycode считается один раз в `__init__` через `XKeysymToKeycode(0xff1b)`).

`popup_rect(name)` — прямоугольник окна попапа: `xprop -root _NET_CLIENT_LIST`, поиск окна с
`WM_NAME = "Eww - <name>"`, затем `GdkX11.X11Window.foreign_new_for_display` и
`get_frame_extents()` — то есть берётся реальная геометрия с учётом размещения WM, а не
предположение из yuck.

`guard(name, token)` — сторож открытого попапа: раз в 60 мс смотрит, не нажата ли кнопка мыши
вне прямоугольника попапа (и ниже панели, `py > 52`) и не нажат ли Escape; в обоих случаях
`close_popups()`. Работает, пока токен в файле совпадает с его токеном.

`toggle(name)` — переключение попапа: если он уже открыт, `close_popups()` и выход; иначе
`close_popups()`, для `apps` — `generate_apps()`, `eww open`, новый токен, запуск
`guard` отдельным процессом.

`icon_path(info)` — путь к иконке приложения из `Gio.DesktopAppInfo` через
`Gtk.IconTheme.lookup_by_gicon` (32 px), иначе `application-x-executable`.

`generate_apps()` — строит `generated.yuck`: берёт избранное и недавние из
`~/.local/state/eww-topbar/initial-state.json` (снимок прежнего меню Whisker) либо из
`menu-state.json` (обновляется при запуске приложений), и генерирует виджеты
`favorite-apps` / `recent-apps` — по две кнопки в строке, с иконкой, именем и
`:onclick "bridge.py launch-app <id>"`. Файл перезаписывается только если текст изменился
(иначе eww перезагружал бы конфиг на каждом открытии).

`listen()` — основной цикл состояния:

* `emit()` печатает JSON только при изменении (иначе eww дёргался бы каждые 2 с);
* `audio()` — `pactl get-default-sink` + `pactl -f json list sinks`: средняя громкость каналов,
  mute, описание выхода, иконка по громкости (`<35`, `<70`, иначе максимум);
* `media()` — первый MPRIS-плеер: `artist — title`, `playing`;
* `tick()` — раз в 2 с обновляет время/дату и заголовок активного окна через
  `xprop _NET_ACTIVE_WINDOW` + `_NET_WM_NAME`; текст окна попадает **только в данные**,
  никогда в командную строку (инъекция через заголовок невозможна), `Eww - …` отфильтрован;
* `pulse_event()` — подписка `pactl subscribe`, события громкости склеиваются дебаунсом
  80 мс (иначе при кручении колеса — шквал обновлений);
* подписка на `PropertiesChanged` MPRIS, SIGTERM/SIGINT корректно гасят дочерние процессы.

`main()` — диспетчер команд:

| Команда | Что делает |
|---|---|
| `listen` | цикл состояния (его вызывает `deflisten`) |
| `generate` | пересобрать `generated.yuck` |
| `toggle <apps\|audio\|calendar\|session>` | открыть/закрыть попап + guard |
| `guard <имя> <токен>` | сторож попапа (внутреннее) |
| `close` | закрыть попапы (кнопка ×) |
| `launch-app <id>` | запустить приложение, обновить «недавние» |
| `wallpaper` | `~/WallpaperEngine/launch.sh` (путь поправь под себя) |
| `theme` | `~/dotfiles/scripts/theme-menu.sh` |
| `mixer` / `appfinder` | `pavucontrol` / `xfce4-appfinder` |
| `lock` / `logout` / `switch-user` | `xflock4` / `xfce4-session-logout [--switch-user]` |
| `mute` / `set-volume <n>` / `volume-scroll <up\|down>` | `pactl` на `@DEFAULT_SINK@`, предел 0–150 % |
| `media <Previous\|PlayPause\|Next>` | MPRIS-вызов первому плееру |

## eww-topbar — управление панелью

* `start` / `restart` — создаёт `~/.config/eww/enabled`, импортирует в user-менеджер
  `DISPLAY`, `XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_CURRENT_DESKTOP`,
  `XDG_SESSION_TYPE` (без этого юнит не видит X-сервер) и запускает `eww-topbar.service`.
* `activate` — ждёт до 4.5 с, пока `eww ping` ответит, проверяет, что окно `topbar`
  загружено, **только потом** гасит `xfce4-panel` (чтобы не остаться без панели, если
  конфиг битый), открывает панель; при ошибке поднимает XFCE обратно. В конце
  перезапускает `smart-clipboard.service`: значок буфера обмена регистрируется в
  StatusNotifier один раз, и после смены «владельца» трея его надо перерегистрировать.
* `stop` — останавливает оба юнита.
* `restore` — убирает флаг `enabled`, гасит юниты, уводит автозапуск в
  `~/.local/state/eww-topbar/eww-topbar.desktop.disabled`, запускает
  `restore-shortcuts.py`, поднимает `xfce4-panel`, уведомляет.
* `status` — `systemctl --user status` обоих юнитов.

`restore-shortcuts.py` удаляет **только** те сочетания, которые поставила панель: читает
`~/.local/state/eww-topbar/shortcuts-added.json` (`ключ → ожидаемое значение`) и снимает
биндинг лишь если текущее значение всё ещё совпадает. Правки пользователя после установки
не затираются.

## Трей: почему нужен xembedsniproxy

Панель XFCE 4.20 не держит XEmbed-лоток: плагин `systray` работает по
StatusNotifierItem + dbusmenu, а `_NET_SYSTEM_TRAY_S0` никому не принадлежит. Eww рисует
SNI-иконки сам, а для старых XEmbed-приложений поднимается `xembedsniproxy`
(юнит `eww-tray-bridge.service`, бинарник из официального пакета Arch, разложен в
`~/.local/opt/eww-topbar`). Отсюда `Environment=LD_LIBRARY_PATH=…/lib` в юните.

## Отладка

```sh
eww-topbar status
journalctl --user -u eww-topbar -u eww-tray-bridge -n 50 --no-pager
~/.config/eww/scripts/bridge.py listen      # посмотреть, что видит панель (JSON в stdout)
~/.local/bin/eww --config ~/.config/eww active-windows
tail -f ~/.local/state/eww-topbar/actions.log
```

Если панель не появилась — сначала `eww ping` и `eww list-windows`; `xfce4-panel` в этот
момент ещё жив (по задумке), поэтому экран без панели не остаётся.
