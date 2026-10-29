# Переключатель оформления XFCE: как устроен и что делает каждая функция

Здесь разобраны `scripts/theme-switch.sh`, `scripts/lib-theme.sh`, `scripts/theme-menu.sh`,
`scripts/install-assets.sh`, `scripts/import-profile.py` и формат профиля
`profiles/macos-bigsur/`. `picom-toggle.sh` — в `02-picom.md`, потому что он неразрывно
связан с конфигом picom.

## 1. Модель: профиль — это каталог

Профиль лежит в `profiles/<имя>/` и бывает двух видов.

**Манифест** (так сделан `macos-bigsur`) — «рецепт», который применяется к текущей системе:

```
profiles/macos-bigsur/
├── manifest.env            переменные профиля (source из bash)
├── xfconf.tsv              канал:::свойство:::тип:::значение
├── xfce4-panel.xml         раскладка панели (верхняя строка)
├── xfce4-panel-plank.xml   та же панель, но без нижнего дока (его отдаём plank)
├── plank/                  темы дока (dock.theme)
└── autostart/plank.desktop автозапуск дока
```

**Точный снимок** (так делаются бэкапы) — копия состояния:

```
profiles/_rollback-<дата>_<время>/
├── xfconf-xml/<канал>.xml  все каналы xfconf как есть
├── xfconf-dump/<канал>.txt вывод xfconf-query -lv (для чтения глазами)
├── config/{panel,autostart,gtk-3.0}
├── inventory.txt           хост, время, темы, шрифт
├── wallpapers.txt          пути обоев
└── manifest.env            заголовок для списка
```

Разница принципиальная: манифест «натягивает» тему на текущие настройки и не трогает то,
чего в нём нет; снимок восстанавливает всё, что было, включая панель и хоткеи.

Поток `apply`: автобэкап текущего → применить профиль → перезапустить панель →
проверить состояние → уведомление. Поток `restore-last`: применить последний `_rollback-*`
без создания нового бэкапа (иначе откат отката плодит мусор).

## 2. theme-switch.sh — точка входа

`SCRIPT_DIR`/`DOTFILES_DIR` вычисляются от расположения скрипта, поэтому репозиторий можно
держать где угодно, но `DOTFILES_DIR` по умолчанию `$HOME/dotfiles`. Дальше подключается
`lib-theme.sh` и создаётся `.state/`.

`usage()` — печатает справку (текст в heredoc, чтобы не зависеть от локали).

`profile_title <каталог>` — берёт `PROFILE_TITLE=` из `manifest.env`, если его нет —
имя каталога. Нужна, чтобы в меню было «macOS Big Sur (WhiteSur)», а не `macos-bigsur`.

`cmd_list` — печатает профили, помечает те, у которых есть `xfconf-xml/`, как
`[точный снимок]`, и строкой ниже — что применено сейчас (`.state/current`).

`cmd_backup [имя]` — создаёт `profiles/<имя>` (по умолчанию `current-<дата>_<время>`),
вызывает `snapshot_state`, пишет минимальный `manifest.env` с датой, уведомляет.
Отказывается работать, если каталог уже существует (`die`).

`cmd_restore_last` — берёт путь из `.state/last-rollback`; если файла нет — самый свежий
`profiles/_rollback-*`; применяет его как обычный профиль с `--no-backup`.

`install_own_launchers` — кладёт наши `.desktop` из `launchers/` в
`~/.local/share/applications`, подставляя `@@HOME@@` (в `Exec=` переменные не раскрываются,
поэтому путь хранится плейсхолдером) и обновляя кэш `update-desktop-database`.

`apply_profile <имя> [--no-backup]` — ядро:

1. проверяет, что профиль существует;
2. `install_own_launchers` (ярлык переключателя всегда должен быть в меню);
3. если не `--no-backup`: снимает снимок в `profiles/_rollback-<метка>`, пишет путь в
   `.state/last-rollback`;
4. если в профиле есть `xfconf-xml/` — `restore_xml_state` (точное восстановление);
5. иначе: `source manifest.env` с `set -a` (все переменные становятся окружением),
   `apply_xfconf_tsv`, `install_panel_layout`, **повторно** `apply_xfconf_tsv`
   (кэш `xfsettingsd` иногда откатывает часть ключей после рестарта панели),
   обои, шрифт (только если `fc-list` его видит), `plank_setup`, `picom_setup`,
   `install_keybindings`;
6. пишет имя профиля в `.state/current`;
7. держит не больше пяти `_rollback-*` (остальные удаляются по времени);
8. `verify_state` + уведомление с подсказкой про откат.

`cmd_show` — `verify_state` плюс текущий профиль и последний автобэкап.

`cmd_import <ссылка> [имя] [флаги]` — импорт чужого репозитория:

* нормализует ссылку: `git@github.com:user/repo.git` → `https://github.com/user/repo`,
  понимает `/tree/<ветка>/<подкаталог>` и суффикс `.git`;
* имя профиля из имени репозитория: нижний регистр, недопустимые символы → `-`;
* клон (или `git pull`, если уже клонирован) в `imports/<имя>` с `--depth=1`;
* передаёт флаги `--dry-run`, `--exact`, `--no-assets`, `--run-installer`
  в `import-profile.py` (пустой массив флагов не передаётся: argparse ругается на
  пустой аргумент);
* при успехе уведомляет, что профиль виден в меню.

В конце — `case` по `$1`: `list`, `apply`, `backup`, `restore-last`, `import`, `show`,
`gui` (exec на `theme-menu.sh`), `-h/--help`, иначе — предупреждение и код 2.

## 3. lib-theme.sh — библиотека

Логирование: `say` (синяя строка `==>`), `warn` (жёлтая, в stderr), `die` (красная, выход 1),
`notify <заголовок> [текст]` — `notify-send` с иконкой темы, молча пропускается, если
`notify-send` нет.

### xfconf

* `xfconf_has <канал> <свойство>` — есть ли свойство.
* `xfconf_set <канал> <свойство> <тип> <значение>` — если свойство есть, меняет значение
  (`-s`), иначе **создаёт** (`-n -t <тип> -s`). Это важно: `xfconf-query -s` не создаёт
  новые ключи и без `-n` отвечает «Свойство не существует».
* `apply_xfconf_tsv <файл>` — читает построчно `канал:::свойство:::тип:::значение`,
  пропускает пустые строки и `#`-комментарии, строки без `:::` игнорирует. Разбор идёт
  через `%%:::*` / `#*:::`, то есть значение может само содержать `:::` в конце.
* `list_channels` — все каналы `xfconf-query -l`, без двоеточий на конце и дублей.

### Снимок и восстановление

* `snapshot_state <каталог>` — сохраняет: `xfconf-dump/<канал>.txt` для каждого канала,
  `xfconf-xml/` (копия `~/.config/xfce4/xfconf/xfce-perchannel-xml`), `config/panel`,
  `config/autostart`, `config/gtk-3.0`, `inventory.txt` (хост, время, GTK/иконки/курсор/
  шрифт/тема окон/раскладка кнопок) и `wallpapers.txt` (`xfce4-desktop` ключи `last-image`).
* `restore_xml_state <профиль>` — возвращает систему в состояние снимка: гасит picom,
  убирает его автозапуск (снимок сам вернёт нужное значение композитора), останавливает
  панель, копирует XML каналов, убивает `xfconfd` (иначе кэш перезапишет файлы), запускает
  панель, восстанавливает `autostart` и перерисовывает рабочий стол (`xfdesktop --reload`).

### Панель

* `stop_panel` — если включён Eww (`~/.config/eww/enabled`), останавливает его юниты;
  затем `xfce4-panel -q`, ждёт до 2.4 с, добивает `pkill`, ждёт и гасит `xfconfd`.
  Порядок и паузы не косметика: работающая панель перезаписывает свой XML, а `xfconfd`
  держит кэш каналов — без остановки обоих раскладка «не применяется».
* `start_panel` — при включённом Eww поднимает `eww-topbar restart`, иначе
  `setsid -f xfce4-panel`, ждёт 1.5 с и проверяет `pgrep`; при неудаче — предупреждение
  с ручной командой.
* `install_launchers` — массив `LAUNCHERS=("id:/путь.desktop" ...)` из `manifest.env`:
  каждому плагину `launcher-<id>` нужен свой каталог `~/.config/xfce4/panel/launcher-<id>/`
  с копией `.desktop`.
* `install_panel_layout <каталог>` — если в профиле есть `PLANK_THEME`, есть
  `xfce4-panel-plank.xml` и установлен `plank`, берётся раскладка без нижней панели (док
  отдан plank). Дальше: `stop_panel`, копирование XML панели, копирование `panel/`-подкаталогов,
  `install_launchers`, `pkill xfconfd`, `start_panel`.

### Обои и шрифт

* `set_wallpaper <путь>` — ставит картинку на **все** мониторы и рабочие столы: берёт
  существующие ключи `.../backdrop/.../last-image`, для каждого ставит путь и
  `image-style = 5` (zoomed), добивает отсутствующие рабочие столы; если ключей нет вообще —
  строит их от `/backdrop/screen0/monitor0/workspaceN` по числу рабочих столов (`xfwm4`).
  В конце `xfdesktop --reload`.
* `font_available <семейство>` — сравнивает с `fc-list : family` через here-string,
  **без пайпа**: при `set -o pipefail` связка `fc-list | grep -q` получает SIGPIPE и даёт
  ложное «шрифта нет».

### Док plank

`plank_setup <каталог>`:

* нет `PLANK_THEME` — гасит plank и удаляет его автозапуск (чтобы чужой док не висел
  поверх другой темы);
* plank не установлен — предупреждение с командой установки, остальное продолжается;
* иначе копирует темы в `~/.local/share/plank/themes`, ставит автозапуск, задаёт через
  `gsettings` путь `net.launchpad.plank.dock.settings:/net/launchpad/plank/docks/dock1/`:
  тему, позицию, размер иконки, режим скрытия, зум 130 %;
* если задан `PLANK_ITEMS` (список `.desktop`), пересобирает
  `~/.config/plank/dock1/launchers/*.dockitem` (`Launcher=file://...`) и прописывает порядок
  в `gsettings dock-items`;
* перезапускает plank через `setsid -f`.

### picom и хоткеи

* `picom_setup <каталог>` — при `PICOM_ENABLE != 1` гасит picom, убирает автозапуск и
  ставит `xfwm4 /general/use_compositing = false`; при `1` вызывает `picom-toggle.sh on`
  (или предупреждает об установке) и пишет `~/.config/autostart/picom.desktop` с
  `Exec=<toggle> on`.
* `install_keybindings` — `Super+P` → `picom-toggle.sh`, `Super+Alt+P` → настройки дисплея
  (чтобы не потерять прежний биндинг), `override = true` для `/commands/custom`.
* `verify_state` — печатает GTK-тему, иконки, курсор, тему окон, факт наличия XML панели и
  её pid, путь обоев. Это дешёвая проверка «применилось ли», не требующая глаз.

## 4. theme-menu.sh — «в один клик»

Собирает одностолбцовый список: действия (`Сделать бэкап`, `Вернуть последний бэкап`,
`Импортировать тему из GitHub`), профили в виде `Название  [ключ]`, затем `_rollback-*`
как «Бэкап <дата>  [ключ]».

Тонкости, найденные на живом zenity 4.2.2:

* `--list` **не** делит строки по `|` на столбцы — поэтому формат один столбец, а ключ
  разбирается из `[...]` в конце строки (`case *"["*"]"`);
* повторяющиеся строки zenity считает ошибкой (`Duplicate item`) и выбирает наугад,
  поэтому список прогоняется через `awk '!seen[$0]++'`.

Выбор обрабатывается `case`: бэкап, откат, импорт (второй диалог `--entry` для ссылки),
применение профиля. Весь вывод команды пишется в `mktemp`-лог, который затем показывается
в `--text-info` с кодом возврата; при ошибке добавляется `zenity --error`. Лог удаляется.

## 5. install-assets.sh — темы без root

Шесть шагов, повторный запуск безопасен:

1. **sassc → dart-sass.** WhiteSur собирается через `sassc`, которого в системе нет:
   ставится `dart-sass` в `~/.local/share/npm-global` и кладётся шим `~/.local/bin/sassc`,
   который переводит флаги libsass (`-t/-s/-I/-p/-m/-a/-C/-M`) в вызовы dart-sass.
2. **Исходники.** `git clone --depth=1` WhiteSur-gtk-theme, WhiteSur-icon-theme,
   WhiteSur-cursors и SmallSur в `~/dotfiles/.build` (существующие клоны не трогаются).
3. **GTK + xfwm4.** `install.sh -c dark -c light -o normal -d ~/.themes` с `SHELL_VERSION=48`
   и `PATH` с шимом.
4. **Иконки и курсоры** в `~/.local/share/icons`; дополнительно ссылка
   `~/.icons/WhiteSur-cursors` → тема курсора, иначе `xfsettingsd` её не находит.
5. **Шрифт Inter** — из последнего релиза `rsms/inter` (GitHub API, `curl`), распаковка в
   `~/.local/share/fonts/Inter`, `fc-cache`.
6. **Обои и иконка Apple-меню.** Обои SmallSur → `~/Изображения/Обои/macos`,
   `apple.svg` из simple-icons с принудительным светлым `fill` (в исходнике `fill` нет,
   и на тёмной панели логотип был бы чёрным).

## 6. import-profile.py — чужой репозиторий в профиль

Функции:

* `walk_dirs(root)` — обход дерева с исключением `.git`, `node_modules`, `docs`, `img` и т.п.
* `parse_channel_xml(path)` — разбирает XML канала xfconf в `{канал: [(свойство, тип,
  значение)]}`; рекурсивно идёт по вложенным `<property>`, массивы сворачивает в последнее
  значение (для одиночных ключей этого достаточно).
* `find_channels(src)` — ищет `*.xml` с `<channel` в первых 400 байтах, возвращает первый
  файл на канал (порядок обхода стабилен).
* `prop(channels, канал, имя)` — значение свойства или `None`.
* `looks_like_gtk_theme` / `looks_like_icon_theme` / `looks_like_cursor_theme` /
  `looks_like_plank_theme` / `looks_like_wallpaper_dir` — эвристики по содержимому
  (`gtk-3.0/`, `index.theme` + `apps/`, `cursors/` + `cursor.theme`, `dock.theme`,
  каталог с именем `wallpaper/background/обои` и картинками). Каталоги-шаблоны
  (`template`, `example`, `skeleton`, `src-`) отбрасываются. `index.theme` для GTK-темы
  не обязателен: XFCE показывает темы из `~/.themes` по наличию подкаталогов.
* `collect_assets(src)` — собирает найденные темы, иконки, курсоры, шрифты (`.ttf/.otf`),
  обои (>300 КБ в каталоге обоев), темы plank; сортирует GTK-темы так, чтобы настоящие
  темы (`theme/`, `themes/`, `.themes/`, с `xfwm4/`) шли первыми; отдельно помечает
  «россыпь картинок» (`icons/ico`, `icons/png` без `index.theme`) — это не тема.
* `find_installers` / `find_build_markers` — находит `install.sh`, `setup.sh`, `build.sh`,
  `meson.build`, `Makefile` и т.п. Установщики **не запускаются**, только печатается
  предупреждение с точной командой; запуск — лишь по флагу `--run-installer`.
* `install_asset(kind, path, dry)` — копирует ассет в `~/.themes`, `~/.local/share/icons`,
  `~/.local/share/plank/themes`, `~/.local/share/fonts`; для курсоров дополнительно создаёт
  ссылку в `~/.icons`; при `dry` только печатает цель.
* `build_profile(...)` — основной сценарий: находит каналы и ассеты, собирает ключи
  `xfconf.tsv` (`xsettings`: тема, иконки, курсор, шрифт, раскладка кнопок; `xfwm4`: тема,
  раскладка, выравнивание заголовка, композитор, прозрачность рамок), при отсутствии
  имён берёт их из имён каталогов, проверяет, что упомянутые темы реально есть в системе,
  иначе предупреждает; обои из чужого конфига принимает только если файл существует;
  копирует раскладку панели, темы дока, обои; ставит ассеты (если не `--no-assets`);
  пишет `manifest.env`; по `--exact` сохраняет `xfconf-xml/`.
* `main()` — argparse (`--src`, `--name`, `--dry-run`, `--exact`, `--run-installer`,
  `--no-assets`) и валидация имени профиля регуляркой `[A-Za-z0-9._-]{1,48}`.

Отчёт печатается в конце списком, предупреждения — отдельным блоком с `!`.

## 7. Профиль macos-bigsur

`manifest.env` — переменные, которые видит `apply_profile`:

| Переменная | Смысл |
|---|---|
| `PROFILE_TITLE`, `PROFILE_DESC` | название и описание для меню/списка |
| `GTK_THEME`, `XFWM_THEME`, `ICON_THEME`, `CURSOR_THEME` | для справки (реально применяет `xfconf.tsv`) |
| `FONT_NAME` | шрифт; применяется только если стоит в системе |
| `WALLPAPER` | абсолютный путь к обоям (`$HOME` раскрывается, файл source-ится bash) |
| `PICOM_ENABLE=1` | включить эффекты и автозапуск |
| `LAUNCHERS=("id:путь" ...)` | какие `.desktop` положить плагинам `launcher-<id>` |
| `PLANK_THEME`, `PLANK_POSITION`, `PLANK_ICON_SIZE`, `PLANK_HIDE_MODE`, `PLANK_ITEMS` | док |

`xfconf.tsv` — только те ключи, которые профиль действительно меняет: GTK-тема, иконки,
курсор и его размер 28, раскладка кнопок `close,minimize,maximize:` (светофор слева),
тема окон WhiteSur, прозрачность рамки 92, центрированный заголовок, `CHM|O`
(свернуть/скрыть/развернуть слева, закрыть справа), тёмный режим панели.
`use_compositing` намеренно отсутствует — им управляет picom.

`xfce4-panel.xml` — верхняя строка высотой 28 px на всю ширину, плагины:
Whisker-меню с иконкой Apple, кнопки запуска, список задач, индикатор, часы, звук,
меню каталога, «показать рабочий стол». `xfce4-panel-plank.xml` — то же без нижней панели,
когда док отдан plank.
