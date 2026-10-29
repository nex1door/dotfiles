# dotfiles — XFCE 4.20 в стиле macOS (CachyOS, X11)

Набор моих дотфайлов для десктопа: XFCE 4.20 с темой WhiteSur, верхняя панель на Eww,
picom со скруглениями и размытием «по белому списку», док plank, переключатель оформления
в один клик (с автоматическим бэкапом и откатом) и мелочи вроде логотипа fastfetch из фото.

Всё проверено на живой машине: CachyOS (rolling, Arch-совместимый), XFCE 4.20.2 / xfwm4 4.20.0,
X11 через lightdm, NVIDIA GTX 1080 (ветка 580xx, DKMS), монитор 3440x1440 (текущий режим 120 Гц, доступны 165/180),
локаль `ru_RU.UTF-8`. Скриншотов в репозитории нет — только конфиги и скрипты.

Главная идея: оформление — это **профиль**, а не россыпь настроек. Профиль применяется одной
командой, перед применением автоматически снимается точный снимок текущего состояния, и любой
снимок можно применить обратно. Поэтому экспериментировать с чужими темами не страшно.

```
~/dotfiles/scripts/theme-switch.sh list
~/dotfiles/scripts/theme-switch.sh apply macos-bigsur
~/dotfiles/scripts/theme-switch.sh restore-last
```

## Быстрый старт

```sh
git clone git@github.com:nex1door/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh --dry-run          # посмотреть, что и куда ляжет
./install.sh                    # разложить по $HOME (с бэкапом существующего)
./install.sh --with-xfconf      # опционально: перезаписать каналы xfconf (нужен релогин)
```

`install.sh` ничего не удаляет: каждый перезаписываемый файл сначала копируется в
`~/.dotfiles-backup-<дата_время>/` с тем же относительным путём. Root не нужен нигде.

Ассеты (темы WhiteSur, иконки, курсоры, шрифт Inter, обои) в репозиторий не входят — они
собираются из апстримов:

```sh
./scripts/install-assets.sh     # без sudo: ~/.themes, ~/.local/share/icons, ~/.local/share/fonts
```

Дальше — либо переключатель тем (`theme-switch.sh apply macos-bigsur`), либо своя настройка поверх.

## Что внутри

| Путь | Что это |
|---|---|
| `scripts/theme-switch.sh` | главная команда: `list/apply/backup/restore-last/import/show/gui` |
| `scripts/lib-theme.sh` | внутренняя библиотека переключателя (xfconf, панель, обои, plank, picom) |
| `scripts/theme-menu.sh` | zenity-меню «в один клик» |
| `scripts/picom-toggle.sh` | включить/выключить picom и согласовать его с композитором xfwm4 |
| `scripts/install-assets.sh` | сборка и установка тем/иконок/курсоров/шрифта/обоев без root |
| `scripts/import-profile.py` | импорт чужого репозитория с GitHub в профиль оформления |
| `profiles/macos-bigsur/` | профиль macOS Big Sur: `manifest.env`, `xfconf.tsv`, раскладка панели, темы plank |
| `launchers/theme-switch.desktop` | ярлык «Оформление XFCE» в меню приложений |
| `config/picom/` | `picom.conf` (picom 11+) и `picom-animations.conf` (форки с анимациями) |
| `config/eww/` | верхняя панель: `eww.yuck`, `eww.scss`, `scripts/bridge.py` (события и действия) |
| `config/fastfetch/` | логотип из фото: `ava.ansi`, `make_logo.sh` (chafa), `gen_logo.py` (PIL) |
| `config/xfce4/xfconf/xfce-perchannel-xml/` | каналы xfconf: панель, хоткеи, обои, темы, шрифты |
| `config/xfce4/` | `helpers.rc` (чем открывать), настройки скриншотера |
| `config/systemd/user/` | user-юниты: Eww, буфер обмена, прокси-мост, ротатор ключей |
| `config/autostart/` | автозапуск: picom, plank, Eww, разгон памяти NVIDIA |
| `config/shell/`, `config/fish/` | `.bashrc`, `.bash_profile`, `.zshrc`, `config.fish`, функции fish |
| `config/btop/`, `config/micro/` | тема btop, настройки редактора micro |
| `local/bin/` | обёртки: `chafa`, `picom`, `sassc`, `nvidia-oc.sh`, `eww-topbar`, `smart_clipboard.py` |
| `docs/` | подробное описание каждой подсистемы и каждой функции скриптов |

Подробности:

* `docs/01-theme-switcher.md` — переключатель тем: каждая функция `theme-switch.sh`,
  `lib-theme.sh`, `theme-menu.sh`, `install-assets.sh`, `import-profile.py`
* `docs/02-picom.md` — правила picom: что и почему блюрится, тени, скругления
* `docs/03-eww-topbar.md` — верхняя панель Eww: виджеты, `bridge.py` (действия, попапы, трей)
* `docs/04-shell-terminal.md` — оболочки, fastfetch-логотип (математика ячейки), btop, micro
* `docs/05-xfce-settings.md` — каналы xfconf, хоткеи, панель, шрифты, обои
* `docs/06-services-binaries.md` — systemd-юниты, автозапуск, локальные обёртки,
  `smart_clipboard.py`
* `docs/07-troubleshooting.md` — таблица «симптом → причина → лечение» из реальных поломок

## Что появляется после установки

```sh
theme-switch.sh list | apply <профиль> | backup [имя] | restore-last | show | gui
theme-switch.sh import <ссылка на GitHub> [--dry-run|--exact|--no-assets|--run-installer]
picom-toggle.sh on | off | toggle | status        # Win+P — то же самое
eww-topbar start | restart | stop | restore | status
```

Клавиши (настраиваются профилем и `install_keybindings`):

| Клавиши | Действие |
|---|---|
| `Super+P` | включить/выключить picom |
| `Super+Alt+P` | настройки дисплея |
| `Super+Q` | закрыть активное окно |
| `Super+W` | свернуть все окна (тумблер) |
| `Super+E` / `Super+B` / `Ctrl+Alt+F` | файловый менеджер |
| `Ctrl+Alt+T` | терминал |
| `Super+Space` | меню приложений (Eww) |
| `Print` / `Shift+Print` | скриншот всего экрана / области |

## Почему это работает именно так (короткие выводы)

* Панель меняется только при остановленных `xfce4-panel` **и** `xfconfd`: работающая панель
  перезаписывает свой XML, а демон держит кэш каналов — иначе раскладка «не применяется».
* `xfwm4 /general/use_compositing` не задаётся профилем: этим ключом управляет picom.
  Два композитора одновременно = грязные края окон.
* `unredir-if-possible = true` усыплял композитор при любом полноэкранном окне, и эффекты
  молча пропадали. Держим `false`, а FPS в играх даёт `Super+P`.
* Размытие — белый список: терминалы, верхняя панель, меню, уведомления. У чужих ARGB-окон
  (Telegram, Steam, браузеры) блюр вылезает из-под рамок, поэтому им он выключен.
* `blur-background-frame = false` — иначе блюр лезет под рамки приложений.
* XFCE ищет курсоры в `~/.icons` и `/usr/share/icons`, а не в `~/.local/share/icons`:
  без ссылки `~/.icons/WhiteSur-cursors` курсор откатывается на имя темы иконок.
* Курсор `xorg-xkill` может быть не установлен — хоткей на `xkill` тогда молча не работает.
  Проверяй, что вызываемый бинарник существует.
* zenity 4.2.2 не разбивает строки `--list` по `|`: список одностолбцовый, ключ профиля
  разбирается из квадратных скобок в конце строки.

## Зависимости

Обязательные: `bash`, `xfconf`, `xfce4-panel`, `zenity`, `python3` (для `import-profile.py`),
`git`, `curl`. Опциональные: `picom`, `plank`, `eww` (для верхней панели), `chafa` (логотип
fastfetch), `dart-sass` (сборка WhiteSur), `libX11` и PyGObject (`python-gobject`, `gtk3`)
для `bridge.py` и `smart_clipboard.py`.

На Arch/CachyOS:

```sh
sudo pacman -S picom plank zenity python-gobject gtk3 libdbusmenu-gtk3 \
               appmenu-gtk-module xfce4-appmenu-plugin
yay -S eww          # или собрать из исходников elkowar/eww
```

## Лицензия и благодарности

Код — MIT (`LICENSE`). Темы и шрифты ставятся из апстримов и живут под своими лицензиями:
WhiteSur (GPL-3.0) и WhiteSur-cursors/иконки — vinceliuice, SmallSur (MIT) — jothi-prasath,
Inter (OFL) — rsms, логотип Apple — simple-icons (CC BY 4.0), используется только как иконка меню.
