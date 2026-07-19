# Declarative Deps List via jdx/mise

*What*: Instruct jdx/mise to make available the utilities from `$HOME/.config/mise/config.toml` to all terminal windows.

*How*: Here is how:
```bash
curl https://mise.jdx.dev/install.sh | sh

echo "eval \"\$(<HOME_DIR>/.local/bin/mise activate bash)\"" >> ~/.bashrc

mkdir -p ~/.config/mise

vim ~/.config/mise/config.toml
```
