function minigpt --description "mini-gpt-cli (train/generate/inspect) из $HOME/Проекты/mini-gpt-cli"
    set -l root $HOME/Проекты/mini-gpt-cli
    command $root/.venv/bin/python $root/cli.py $argv
end