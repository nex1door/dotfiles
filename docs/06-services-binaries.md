# Юниты systemd --user, автозапуск, локальные обёртки

## Юниты `config/systemd/user/`

User-менеджер стартует вместе с сеансом, поэтому юниты с `WantedBy=default.target`
поднимаются при логине — без root и без systemd-системных файлов.

### `smart-clipboard.service`

```ini
After=graphical-session.target
PartOf=graphical-session.target
ConditionEnvironment=XDG_SESSION_TYPE=x11
ExecStart=/usr/bin/python3 %h/.local/bin/smart_clipboard.py --limit 25
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=full
ProtectControlGroups=yes
ProtectKernelTunables=yes
RestrictSUIDSGID=yes
```

* только X11: в Wayland `Gtk.Clipboard` работает иначе, сервис там не нужен;
* **именно `/usr/bin/python3`** — системный интерпретатор с PyGObject. Python из venv/uv
  модуль `gi` не видит, и сервис падает с `ModuleNotFoundError`;
* `PrivateTmp=yes` использовать нельзя: X11-сокет лежит в `/tmp/.X11-unix`;
* `DISPLAY`/`XAUTHORITY` приходят из окружения user-менеджера
  (проверка: `systemctl --user show-environment | grep DISPLAY`);
* база и lock — в `~/.local/share/smart-clipboard/`, домашний каталог доступен.

Включение: `systemctl --user enable --now smart-clipboard.service`.

### `eww-topbar.service` и `eww-tray-bridge.service`

`eww-topbar`: `ExecStartPre` генерирует `generated.yuck` (`bridge.py generate`),
затем `eww --config %h/.config/eww --no-daemonize daemon`, `ExecStartPost` — `eww-topbar activate`
(тот сначала проверяет, что панель реально загрузилась, и только потом гасит XFCE).
`Restart=on-failure`, `RestartSec=2`, `StartLimitBurst=4` за 30 с — защита от цикла падений.
`KillMode=control-group` — гасит вместе с дочерними процессами.

`eww-tray-bridge`: `xembedsniproxy` (мост XEmbed → StatusNotifier) с
`LD_LIBRARY_PATH=%h/.local/opt/eww-topbar/lib` и `QT_QPA_PLATFORM=xcb`,
`PartOf=eww-topbar.service` (живёт и умирает вместе с панелью).

### `agy-proxy-bridge.service`, `token-rotator.service`

Это обёртки вокруг **локальных проектов**, которых в репозитории нет — юниты оставлены как
пример «как запускать своё локальное API-прокси в user-сеансе»
(`ExecStart=%h/programms/...`, `Restart=on-failure`/`always`, `WorkingDirectory`).
Без соответствующих каталогов юниты просто не запустятся — это ожидаемо.
`api-keys.txt` и любые ключи в репозиторий не входят и закрыты `.gitignore`.

## Автозапуск `config/autostart/`

| Файл | Что запускает |
|---|---|
| `picom.desktop` | `@@HOME@@/dotfiles/scripts/picom-toggle.sh on` — эффекты при входе |
| `plank.desktop` | `plank` — док |
| `nvidia-oc.desktop` | `nvidia-oc.sh` — профиль производительности и разгон памяти GPU |
| `eww-topbar.desktop` | `eww-topbar start` с задержкой 2 с |
| `tgproxy.desktop` | `tg-ws-proxy` (локальный WS-прокси для Telegram) |

Автозапуски с адресами домашней сети (sftp-монтирование) и внешними приложениями
(wallhaven-движок обоев) в репозиторий сознательно не попали — они привязаны к конкретной
машине и её окружению.

Управление без графики:

```sh
ls ~/.config/autostart
sed -i 's/^X-GNOME-Autostart-enabled=.*/X-GNOME-Autostart-enabled=false/' ~/.config/autostart/picom.desktop
```

## Локальные обёртки `local/bin/`

Смысл всех обёрток один: «если есть системный пакет — берём его, иначе локальная сборка в
`~/.local/opt`». Так можно пользоваться инструментом без root и без «лечения» пакетов потом.

`chafa`:

```sh
if [ -x /usr/bin/chafa ]; then exec /usr/bin/chafa "$@"; fi
LD_LIBRARY_PATH=$HOME/.local/opt/chafa/usr/lib … exec $HOME/.local/opt/chafa/usr/bin/chafa "$@"
```

Пакет распакован из официального архива CachyOS (подпись проверена) в `~/.local/opt/chafa`,
зависимости (glib2, libheif, libjxl, librsvg, libwebp, libavif) в системе уже есть.
Как только `pacman -S chafa` появится — обёртка начнёт использовать его.

`picom` — то же для picom: системный `/usr/bin/picom` в приоритете, иначе
`~/.local/opt/picom/bin/picom` с `LD_LIBRARY_PATH` на локальный libconfig.

`sassc` — шим libsass → dart-sass (подробно в `01-theme-switcher.md`): WhiteSur собирается
вызовами `sassc`, которого в системе нет. Шим переводит `-t/-s/-I/-p/-m/-a/-C/-M`
в аргументы dart-sass. Удалять его нельзя, иначе пересборка темы ломается.

`nvidia-oc.sh` — профиль производительности при входе:

```sh
sleep 4                                  # ждём готовности X-сервера
export DISPLAY=${DISPLAY:-:0}
# XAUTHORITY: /run/user/$UID/lyxauth, иначе ~/.Xauthority
nvidia-settings -a "[gpu:0]/GPUPowerMizerMode=1"                    # Prefer Maximum Performance
nvidia-settings -a "[gpu:0]/GPUMemoryTransferRateOffset[3]=900"      # +900 MHz к памяти
```

Первая строка — режим питания (не «оптимальный»), вторая — разгон памяти. Разгон памяти
безопаснее разгона ядра и почти не даёт артефактов, но это всё равно разгон: при
нестабильности (`nvidia-smi` показывает ошибки Xid, игры падают) значение надо снижать.
Ошибки глушатся (`>/dev/null 2>&1`), чтобы автозапуск не сыпал уведомлениями.

`eww-topbar` — разобран в `03-eww-topbar.md`.

## `smart_clipboard.py` — менеджер буфера обмена

Свой менеджер истории буфера для X11: GTK3 + StatusNotifierItem (иконка в трее) + меню
через D-Bus. Никаких внешних зависимостей, кроме PyGObject (`gi`).

Ключевые части:

* `HistoryDB` — SQLite-история (`~/.local/share/smart-clipboard/history.db`):
  `add_text` возвращает `("new", id)` или `("dup", id)`; подряд идущий дубликат не плодит
  строку, а обновляет `last_used_at`; `touch` поднимает запись наверх; `delete_ids`,
  `recent(limit)`, `count`.
* `sanitize` / `content_hash` / `make_preview` — чистка (NUL-байты), хэш для поиска
  дубликатов, превью в одну строку (переносы схлопываются, длинное обрезается с `…`,
  кириллица не рвётся).
* `classify` — иконка по содержимому: URL → глобус, e-mail → письмо, код → скрипт,
  иначе текст.
* `menu_model` / `build_menu_tree` — модель меню (шапка со счётчиком, записи, разделитель,
  «Очистить историю», «Выход») и её сериализация в `GLib.Variant` для `com.canonical.dbusmenu`.
* `ClipboardService` — D-Bus-сервис `org.kde.StatusNotifierItem-<pid>-1`: объекты
  `/StatusNotifierItem` и `/MenuBar`, `Activate` (показать меню), `SecondaryActivate`,
  `Scroll`, обработка вызовов меню, «вставить выбранное» (возврат текста в буфер и эмуляция
  вставки), одиночный экземпляр через lock-файл, корректное завершение по сигналам.
  Иконка в трее ищется в теме, а если её нет — рисуется сама (`render_icon`, ARGB через
  `ctypes`+PNG-энкодер без PIL) и ставится в `~/.local/share/icons`.
* `--popup` — попросить уже запущенный сервис показать меню (SIGUSR1), удобно для хоткея.
* `--self-test` — самопроверка без GUI: БД, превью, модель меню, D-Bus-дерево, иконки,
  классификация. Возвращает 0/1, годится для CI.

Флаги: `--limit N` (сколько записей в меню, по умолчанию 25), `--width N` (ширина превью),
`--no-time` (без времени), `--icon-name`, `--icon-mode theme|pixmap|both`, `--db PATH`,
`--self-test`, `--popup`, `-v`.

Проверка:

```sh
/usr/bin/python3 ~/.local/bin/smart_clipboard.py --self-test
systemctl --user restart smart-clipboard.service
journalctl --user -u smart-clipboard -n 30 --no-pager
```
