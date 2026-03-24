# Source .bashrc for login shells.
# bwrap sandboxes launch bash as a login shell, which reads .bash_profile
# but not .bashrc directly.
if [ -f ~/.bashrc ]; then
    source ~/.bashrc
fi
