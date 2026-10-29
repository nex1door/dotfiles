# Настройки XFCE: каналы xfconf, хоткеи, панель, шрифты

Всё состояние рабочего стола XFCE живёт в xfconf: канал — это группа настроек, свойство —
ключ. Файлы каналов лежат в `~/.config/xfce4/xfconf/xfce-perchannel-xml/<канал>.xml`, но
править их при живой сессии бессмысленно: демон `xfconfd` держит кэш и перезапишет файл.
Менять — только через `xfconf-query`.

```sh
xfconf-query -c <канал> -lv                    # всё содержимое канала
xfconf-query -c <канал> -p <свойство> -s <v>   # изменить существующее
xfconf-query -c <канал> -p <свойство> -n -t string -s <v>   # создать (без -n — ошибка)
xfconf-query -c <канал> -r -p <свойство>       # снять (в XML останется type="empty")
```

## Какие каналы здесь лежат

| Канал | Что в нём |
|---|---|
| `xsettings` | GTK-тема `WhiteSur-Dark`, иконки `WhiteSur-dark`, курсор `WhiteSur-cursors` 28 px, шрифт `Inter 11`, раскладка кнопок окна |
| `xfwm4` | тема окон, `CHM\|O`, прозрачность рамки 92, центрированный заголовок, поведение фокуса/перемещения, разбивка на тайлы |
| `xfce4-panel` | одна панель на всю ширину, 28 px, тёмный режим, набор плагинов |
| `xfce4-keyboard-shortcuts` | все сочетания (таблица ниже) |
| `xfce4-desktop` | обои на все рабочие столы (`image-style = 5`, «zoom»), размер иконок 54, стиль |
| `xfce4-notifyd` | уведомления (в т.ч. ограничение лога) |
| `xfce4-power-manager` | профиль `performance`, DPMS выключен (`dpms-enabled = false`), «засыпание» экрана не работает — это осознанно для десктопа |
| `xfce4-session` | имя сеанса, обычный X11-сеанс без сохранённых клиентов |
| `xfce4-screensaver`, `xfce4-appfinder`, `xfce4-terminal`, `xfce4-settings-*` | мелкие настройки соответствующих программ |
| `thunar`, `thunar-volman` | файловый менеджер и автомонтирование |
| `displays` | профиль монитора: DP-0, 3440x1440, 120 Гц, масштаб 1 |
| `keyboards`, `pointers` | NumLock выключен; для мыши — libinput, high-resolution wheel |

В `displays.xml` поле `EDID` заменено нулями: это отпечаток конкретного монитора, публиковать
его незачем. При первом запуске XFCE пересчитает его сам.

## Горячие клавиши (как в XML)

| Клавиши | Действие |
|---|---|
| `Super+Q` | закрыть активное окно (`close_window_key`) |
| `Super+W` | свернуть все окна — тумблер (`show_desktop_key`) |
| `Ctrl+Alt+D` | то же (штатный биндинг сохранён) |
| `Super+T` | `alacritty` |
| `Ctrl+Alt+T` | `exo-open --launch TerminalEmulator` |
| `Super+E`, `Super+B`, `Ctrl+Alt+F` | `thunar` |
| `Super+R` | `xfce4-appfinder -c` |
| `Alt+F1` | меню приложений XFCE |
| `Alt+F2` / `Alt+F3` | appfinder (свёрнутый / полный) |
| `Super+Space` | меню приложений Eww (`bridge.py toggle apps`) |
| `Super+P` | включить/выключить picom (`picom-toggle.sh`) |
| `Super+Alt+P` | настройки дисплея |
| `Print` | скриншот всего экрана |
| `Alt+Print` | скриншот окна |
| `Shift+Alt+…` (стрелки, PageUp/Down) | поднять/опустить окно |
| `Ctrl+Shift+Esc` | менеджер задач |
| `Ctrl+Alt+L` | блокировка (`xflock4`) |
| `Ctrl+Alt+Del` | диалог выхода |
| `XF86Audio*` | громкость и медиа — через `bridge.py` (pactl/MPRIS), без плагина PulseAudio |
| `XF86Display`, `XF86WWW`, `XF86Mail` | дисплеи, браузер, почта |
| `Super+KP_*` | тайлинг окна по половинам/углам |
| `Ctrl+F1..F12` | переключение рабочих столов |

`Super+Q` и `Super+W` живут в `/xfwm4/custom/*`, остальные — в `/commands/custom/*`; два
биндинга на одну комбинацию конкурируют за grab, лишний надо снимать через `-r`.
Перед выводом «хоткей не работает» проверь, что вызываемый бинарник существует (пример:
`xorg-xkill` может быть не установлен, и биндинг на `xkill` молча ничего не делает).

## Панель

`xfce4-panel.xml`: одна панель, `position = p=6;x=0;y=0` (сверху по центру), длина 100 %,
28 px, иконки 16 px, `background-style = 1` (сплошной цвет) с `rgba(20,20,22,0.78)`,
`position-locked = true`, `enable-struts = true` (окна не заезжают под панель).

Плагины по порядку: `whiskermenu` (иконка `apple-menu`, ширина 420, категории слева),
запуск приложений, список задач, индикатор, часы, звук, меню каталога, «показать рабочий
стол». Плагинам `launcher-<id>` нужны каталоги `~/.config/xfce4/panel/launcher-<id>/` с
`.desktop` — их раскладывает `install_launchers` из `manifest.env`.

Когда включён Eww, панель XFCE не запускается вовсе (`~/.config/eww/enabled`), а
`lib-theme.sh` в этом случае поднимает/гасит именно Eww.

## Раскладка кнопок окна

`xsettings /Gtk/DecorationLayout = "close,minimize,maximize:menu,icon"` и
`xfwm4 /general/button_layout = "CHM|O"` — «светофор» слева, служебные кнопки справа,
заголовок по центру (`title_alignment = center`). Тема WhiteSur рисует их в стиле macOS;
сам порядок задаётся этими двумя ключами, а не темой.

## Шрифты, курсоры, обои

* Шрифт интерфейса — `Inter 11`. `apply_profile` ставит его только если `fc-list` его видит,
  иначе пропускает с предупреждением (иначе GTK уходит в фолбэк и всё «прыгает»).
* Курсор — `WhiteSur-cursors` 28 px. XFCE ищет темы курсоров в `~/.icons` и
  `/usr/share/icons`, поэтому `install-assets.sh` создаёт ссылку
  `~/.icons/WhiteSur-cursors` → `~/.local/share/icons/WhiteSur-cursors`. Без ссылки
  `xfsettingsd` откатывает курсор на имя темы иконок (`elementary`).
* Обои — `xfce4-desktop/backdrop/screen0/monitorDP-0/workspaceN/last-image`,
  `image-style = 5` (zoom). `set_wallpaper` проставляет путь на все мониторы и рабочие столы,
  а не только на текущий — иначе при переключении стола обои «пропадают».

## Мелочи, которые тоже здесь

* `config/xfce4/helpers.rc`: `TerminalEmulator=alacritty`, `MailReader=sylpheed-claws` —
  чем открывать «терминал» и «почту» из `exo-open`.
* `config/xfce4/xfce4-screenshooter`: каталог сохранения `@@HOME@@/Pictures`, формат PNG,
  действие «сохранить», показывать мышь и рамку. Путь подставляется при установке —
  поправь, если у тебя локализованные каталоги (`~/Изображения`).
* `config/mimeapps.list`: чем открывать `mailto`, `discord://`, `d2mm://`, exe/msi
  (PortProton), `application/octet-stream` и `x-executable` (Alacritty), python/java/markdown/html/json
  (Zed), docx (File Roller).
* `config/user-dirs.dirs`: XDG-каталоги по-русски (`Рабочий стол`, `Загрузки`, `Документы`,
  `Изображения`, `Видео`, `Музыка`, `Шаблоны`, `Общедоступные`) плюс `XDG_PROJECTS_DIR=~/Проекты`.
  Скрипты не должны хардкодить английские имена — только `xdg-user-dir`.
* `config/plank/dock1/launchers/*.dockitem`: элементы дока (`Launcher=file:///usr/share/applications/…`).
  Порядок хранится в `gsettings net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/`.

## Применение каналов из репозитория

```sh
./install.sh --with-xfconf --only xfce
```

Скрипт копирует XML с бэкапом, но предупреждает честно: работающий `xfconfd` может затереть
файлы своим кэшем. Надёжный путь — выйти из сеанса и войти снова (или
`xfce4-panel -q; pkill xfconfd` перед копированием, что и делает `lib-theme.sh`).

Безопаснее и привычнее — не копировать каналы целиком, а применять профиль:
`theme-switch.sh apply macos-bigsur` меняет только те ключи, что перечислены в `xfconf.tsv`,
и делает снимок для отката.
