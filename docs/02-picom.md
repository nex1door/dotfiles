# picom: скругления, тени, размытие — и переключатель Win+P

picom здесь отвечает за всю «дорогую» часть внешнего вида: скругления 12 px, мягкие тени,
размытие под панелью/меню/терминалами и плавное появление окон. Встроенный композитор xfwm4
при этом **выключен** — два композитора одновременно дают грязные края и рассыпающийся блюр.

Файлы:

| Файл | Для чего |
|---|---|
| `config/picom/picom.conf` | обычный picom 11+ (современный синтаксис `rules = (...)`) |
| `config/picom/picom-animations.conf` | форки с анимациями (ft-labs, pijulius, compfy): старый синтаксис |
| `scripts/picom-toggle.sh` | включение/выключение и согласование с xfwm4 |

## picom-toggle.sh — по функциям

`notify` — уведомление `notify-send`, молча пропускается без него.

`compositing <bool>` — единственное место, где меняется
`xfwm4 /general/use_compositing`. Выключение композитора xfwm4 обязательно перед стартом
picom, иначе два композитора конфликтуют.

`picom_bin` — какой бинарник брать: `/usr/bin/picom`, если он есть (системный пакет),
иначе `~/.local/bin/picom` (локальная обёртка на сборку в `~/.local/opt/picom`).

`picom_pid` — pid живого picom: сначала из `~/.cache/picom.pid`, с проверкой, что процесс
жив и в его `cmdline` есть `picom` (защита от переиспользования pid); иначе `pgrep -x picom`.
`running` — булев вариант для `if`.

`is_animation_fork` — `picom --version` ищет в выводе `pijulius|ft-labs|arian|compfy|
simpleanims|yaoccc|animations`. По этому признаку выбирается конфиг.

`pick_config` — `picom.conf` или, если это форк с анимациями, `picom-animations.conf`.

`start_picom` — проверяет наличие бинарника и конфига, копирует `*.conf` из репозитория в
`~/.config/picom` (чтобы лежали рядом с логом), выключает композитор xfwm4, убивает старый
picom, запускает `setsid -f <bin> --config <cfg> --log-file ~/.cache/picom.log
--write-pid-path ~/.cache/picom.pid`, ждёт 1.5 с и проверяет, что процесс жив. При неудаче
присылает уведомление с путём к логу.

`stop_picom` — убивает picom, удаляет pid-файл и **не включает** обратно композитор xfwm4:
«выключить эффекты» значит выключить композитинг совсем (это и есть режим максимального FPS).

Команды: `on`, `off`, `toggle` (по умолчанию, висит на `Super+P`), `status` (pid + конфиг +
лог либо «выключен» и состояние композитора xfwm4).

## picom.conf — что за что отвечает

### Общее

```ini
backend = "glx";              # на NVIDIA glx быстрее xrender
vsync = true;                 # монитор 165 Гц: без разрывов
use-damage = true;            # перерисовывать только повреждённое
detect-rounded-corners = true;
detect-client-opacity = true;
detect-transient = true;
xrender-sync-fence = true;    # нужно драйверам с explicit sync (nvidia)
unredir-if-possible = false;  # см. ниже — это важное решение
log-level = "warn";
```

`unredir-if-possible = true` — классическая ловушка: композитор «засыпает», как только
появляется полноэкранное окно (даже полноэкранный просмотрщик Telegram), и эффекты молча
исчезают. Держим `false`, а производительность в играх даёт `Super+P` (picom выключается
целиком).

### Тени

`shadow = true`, `shadow-radius = 28`, `shadow-opacity = 0.42`, смещение `-18/-14`,
`crop-shadow-to-monitor = true`. Крупная мягкая тень «вниз-влево» — как у окон macOS.

### Скругления

`corner-radius = 12`. Отдельные правила снижают/обнуляют радиус для панелей, доков,
полноэкранных окон и подсказок.

### Размытие

`blur-method = "dual_kawase"`, `blur-strength = 4` (при 6 — «мыло»), глобально
`blur-background = false`. Размытие включается только правилами (белый список).
`blur-background-frame = false` — под рамками окон не блюрим, иначе блюр вылезает по краям.

### Прозрачность и плавность

`frame-opacity = 1.0` (прозрачность рамок — дело темы WhiteSur), `fading = true`,
`fade-in-step = 0.028`, `fade-out-step = 0.05`, `fade-delta = 8`.

### Правила (применяются по порядку, побеждает последнее совпадение)

| Правило | Что делает |
|---|---|
| `window_type = 'desktop'` | обои: без тени, радиуса и блюра |
| `class_g = 'xfce4-panel'` или док, кроме Plank | верхняя строка: без тени, `blur-background = true` |
| `name = 'Eww - topbar'` | стеклянная панель Eww: радиус 13, блюр |
| `name *= 'Eww - '` (остальные окна Eww) | попапы панели: тень, радиус 17, блюр |
| `class_i = 'plank'` | док: без тени/радиуса/блюра/затухания |
| `class_g = 'Wrapper-2.0'` | панельные апплеты — это кнопки, эффекты не нужны |
| `window_type = 'notification'` | уведомления: тень, радиус 14, блюр |
| `menu/popup_menu/dropdown_menu/combo` | меню и выпадающие списки: радиус 10, блюр |
| `tooltip/dnd` | подсказки и drag&drop: без эффектов |
| `Alacritty / Xfce4-terminal / kitty` | терминалы: `opacity = 0.94` + блюр |
| `Xfce4-screensaver` | блокировка: без эффектов |
| Telegram | без блюра (тень оставлена) |
| Steam/steamwebhelper | без эффектов |
| Wine/lutris/heroic/gamescope/Project Zomboid | без эффектов: игры не должны платить за композитор |
| firefox/chromium/brave/chrome | без блюра |
| electron (code, discord, slack, signal, Element), qBittorrent, KeePassXC, virt-manager | без блюра |
| mpv/vlc/obs/gimp/krita/libreoffice/audacity | без блюра |
| thunar, xfdesktop, ristretto, parole, mousepad, galculator, pavucontrol, appfinder, taskmanager | без блюра |
| `fullscreen` | последнее слово: без радиуса, тени, блюра и затухания |

Логика белого списка: у чужих ARGB-окон (мессенджеры, браузеры, Electron) блюр заезжает
под рамки и выглядит грязно, поэтому блюр получают только те окна, где он читается как
«вибрация» macOS — терминалы, панель, меню, уведомления.

## picom-animations.conf — вариант для форков

Форки (`ft-labs/picom`, `pijulius/picom`, `compfy`, `arian8j2`) основаны на picom 11 и
**не понимают** `rules = (...)`; зато понимают `shadow-exclude`, `blur-background-exclude`,
`rounded-corners-exclude`, `opacity-rule`, `fade-exclude` и блок `animations`. Поэтому файл
самодостаточный (без `@include`) и написан на старом синтаксисе; политика размытия в нём та
же, реализованная отрицанием в списках исключений.

Анимации: `animation-for-open-window = "zoom"`, `animation-for-unmap-window = "zoom"`,
`animation-for-transient-window = "slide-up"`, пружина `stiffness` 140/120, масса 0.5,
`dampening = 18`, `clamping = true`.

Выбор файла автоматический: `pick_config` в `picom-toggle.sh` смотрит на `picom --version`.
Обычный picom прочтёт этот файл тоже (ключи `animations` просто не знает, но остальное
примет), поэтому вручную подсовывать его v13 не нужно.

## Проверка без глаз

```sh
picom-toggle.sh status                                  # pid, конфиг, лог
xfconf-query -c xfwm4 -p /general/use_compositing       # должно быть false при работающем picom
tail -n 20 ~/.cache/picom.log                           # ошибок быть не должно
```

Максимальный горизонтальный градиент по скриншоту (PIL) в полосе дока — численная проверка
«блюр есть/нет»: у размытого края градиент в 5–10 раз ниже, чем у резкого.
`picom-inspect` прототипный: окно выбирается неочевидно, лучше опираться на скриншоты.
