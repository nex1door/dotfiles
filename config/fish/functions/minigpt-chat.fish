function minigpt-chat --description "Интерактивный REPL mini-gpt-cli на последнем демо-чекпоинте"
    set -l root $HOME/Проекты/mini-gpt-cli
    set -l ckpt $root/runs/demo/best.pt
    test -f $ckpt; or set ckpt $root/runs/demo/final.pt
    test -f $ckpt; or begin
        echo "minigpt-chat: чекпоинт не найден в $root/runs/demo" >&2
        echo "сначала обучите: minigpt train --demo --epochs 3" >&2
        return 1
    end
    command $root/.venv/bin/python $root/cli.py generate --model-path $ckpt --interactive $argv
end