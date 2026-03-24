# Homebrew
eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"

# direnv (auto-activates .venv when entering the project directory)
eval "$(direnv hook bash)"

# Show active venv in prompt when direnv is managing it
show_virtual_env() {
  if [[ -n "$VIRTUAL_ENV" && -n "$DIRENV_DIR" ]]; then
    echo "($(basename $VIRTUAL_ENV))"
  fi
}
export -f show_virtual_env
PS1='$(show_virtual_env)'$PS1
