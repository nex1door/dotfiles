# Оболочки, fastfetch-логотип, btop, micro

## Оболочки

Три конфига, все тонкие: основное лежит в дистрибутивных файлах CachyOS, здесь — только
личные добавления.

`config/shell/bashrc` (`~/.bashrc`): выход для неинтерактивного шелла
(`[[ $- != *i* ]] && return`), цветные `ls` и `grep`, `PS1='[\u@\h \W]\$ '`, и два блока
`PATH` — `~/.local/bin` (локальные обёртки) и `~/.lmstudio/bin` (CLI LM Studio).

`config/shell/bash_profile` (`~/.bash_profile`): подключает `~/.bashrc` и повторяет те же
`PATH` (логин-шелл не читает `.bashrc` на Arch, если его не подключить явно).

`config/shell/zshrc` (`~/.zshrc`): `source /usr/share/cachyos-zsh-config/cachyos-config.zsh`
плюс те же два `PATH`.

`config/fish/config.fish`: `source /usr/share/cachyos-fish-config/cachyos-config.fish`
(там же `function fish_greeting; fastfetch; end` — приветствие и есть fastfetch),
`~/.local/bin` в начало `PATH`, `~/.lmstudio/bin` в конец. Заготовка `fish_greeting`
закомментирована — чтобы было видно, где её переопределять.

`config/fish/functions/agy.fish` — пример fish-функции для внешнего CLI:
`function agy --description '…'; python3 "$HOME/.local/share/agy-proxy/agy_cachyos_proxy.py" $argv; end`.
Такие функции подхватываются автоматически из `~/.config/fish/functions/` и работают из
любого каталога; правильнее держать их отдельными файлами, а не дописывать в `config.fish`.

Важно про запуск: инструменты, которые вызывают `bash`, fish-синтаксис не понимают.
Активация venv в fish — `source .venv/bin/activate.fish`, проверка функций —
`fish -c 'agy --help'`.

## fastfetch: логотип из фотографии

Идея: фото рендерится в ANSI-арт и подключается как файл-логотип. Никакого нативного
`sixel`/`kitty` тут нет и быть не может (alacritty их не поддерживает), `--logo-type chafa`
не используется — нужен именно `logo.type = "file"`.

```
config/fastfetch/
├── config.jsonc     logo.type=file, source=~/.config/fastfetch/ava.ansi, список модулей
├── ava.ansi         готовый арт (40 колонок)
├── make_logo.sh     рендер через chafa
└── gen_logo.py      альтернативный рендер через PIL (полублоки)
```

`config.jsonc`: логотип-файл с отступами (сверху 2, справа 3), модули:
`title, separator, os, kernel, uptime, packages, shell, display, de, wm, wmtheme, theme,
icons, font, cursor, terminal, cpu, gpu, memory, swap, disk, localip, locale`.

### make_logo.sh — математика ячейки

```sh
./make_logo.sh [COLS] [IMAGE]      # COLS по умолчанию 40, IMAGE — ~/Изображения/ava.jpg
```

* `FONT_RATIO=0.4261` — отношение **ширины** ячейки к её высоте для шрифта alacritty по
  умолчанию (ячейка 9.375 × 22.0 px). Именно W/H, а не наоборот: перевёрнутая ориентация
  даёт в разы завышенную высоту (40×94 вместо 40×17), и chafa молча рисует «полоску».
* `ROWS = round(COLS * aspect * FONT_RATIO)`, где `aspect = 1.0054` — пропорции исходного
  фото (квадрат-ish).
* Сам рендер: `chafa -f symbols --probe=off -s ${COLS}x${ROWS} --font-ratio=$FONT_RATIO
  -c full --symbols block+space --color-space din99d -w 9`. Классы `block` и `quad` дают
  одинаковый результат; `--symbols all` тянет глифы из Symbols for Legacy Computing, которых
  нет в Noto Sans Mono, и они превращаются в квадраты.
* Скрипт печатает число ячеек и размер файла — по этим числам видно, не «схлопнулся» ли арт.

Практика: 40 колонок — разумный минимум (36 заметно хуже по детализации), 48+ детальнее, но
блок шире. Окно терминала должно быть шире логотипа + информации: 40 + 3 + ~68 ≈ 111 колонок,
иначе fastfetch переносит строки.

При смене шрифта или его размера ячейка меняется — `FONT_RATIO` надо перемерить: отрисовать
сетку 24×12 из блоков `U+2588`, снять скриншот окна и разделить ширину/высоту сетки на 24 и 12.

### gen_logo.py — вариант без chafa

`build(src, cols, ratio)`:

1. `Image.open(...).convert("RGB")`, `rows = round(cols * (h/w) / ratio)`, где `ratio` —
   **высота/ширина** ячейки (по умолчанию 2.347, то есть 22.0/9.375);
2. «cover»-подгонка: `scale = max(px_w/w, px_h/h)`, ресайз LANCZOS, центральный кроп до
   `cols × rows*2` пикселей — пропорции не искажаются, лишнее обрезается;
3. каждая ячейка — символ `▀` (U+2580): foreground = верхний пиксель, background = нижний;
   ANSI-последовательности меняются только при смене цвета (файл меньше), строка
   заканчивается `\033[0m`.

`main()` — argparse (`--in`, `--out`, `--cols`, `--ratio`), создаёт каталог и печатает
число строк и байт. Артефактов у полублоков меньше, детализации — тоже; chafa обычно
выразительнее.

## btop

`config/btop/btop.conf` — почти дефолт с несколькими решениями:

* `color_theme = "Default"`, `theme_background = true`, `truecolor = true` — 24-битный цвет,
  фон закрашивается (нужен непрозрачный терминал);
* `shown_boxes = "cpu mem net proc"` — без дисков и GPU в основном экране;
* `update_ms = 100` — 10 Гц: заметно живее дефолтных 2 с, нагрузка в пределах шума;
* `proc_sorting = "cpu lazy"` — сортировка по CPU без «прыжков» каждые 100 мс;
* `rounded_corners = true`, `terminal_sync = true` (синхронизированный вывод — меньше мерцания);
* `vim_keys = false` — обычные стрелки, чтобы не конфликтовать с привычками;
* `presets` — три готовых раскладки (cpu+proc, cpu+mem+net, cpu+net).

## micro

`config/micro/settings.json` — одна строка смысла: `"colorscheme": "catppuccin-macchiato"`.
Схема лежит в `~/.config/micro/colorschemes/` и в репозиторий не входит; без неё micro
откатится на дефолтную, ничего не сломав.

## Проверка

```sh
fastfetch --config ~/.config/fastfetch/config.jsonc | head -5   # логотип и шапка
~/.config/fastfetch/make_logo.sh 40                            # перегенерация арта
python3 ~/.config/fastfetch/gen_logo.py --cols 40              # альтернатива
btop --utf-force                                               # тема и раскладка
```
