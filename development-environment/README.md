# Declarative Deps List via jdx/mise

*What*: Instruct jdx/mise to make available the utilities from `$HOME/.config/mise/config.toml` to all terminal windows.

*How*: Here is how:
```bash
curl https://mise.jdx.dev/install.sh | sh

echo "eval \"\$(<home-dir>/.local/bin/mise activate bash)\"" >> ~/.bashrc

mkdir -p ~/.config/mise

vim ~/.config/mise/config.toml
```


# Git Setup with SSH Authentication and Auto Commit Signing(Verified Badge)

*What*: The title is clear enough.

*How*: Run these commands:
```bash
# Generate keys
ssh-keygen -t ed25519 -C "<email-address>" -f ~/.ssh/<key-name>

# Declare your identity
git config --global user.name "<name>"
git config --global user.email "<email>"

# Tell git to sign with SSH instead of GPG
git config --global gpg.format ssh

# Point git at your existing public key
git config --global user.signingkey ~/.ssh/<key-name>.pub

# Sign all commits automatically
git config --global commit.gpgsign true

# Go to register the keys into the github account
## Paste that public key into GitHub → Settings → SSH and GPG keys -> Select Authentication keys option
## Paste that public key into GitHub → Settings → SSH and GPG keys -> Select Signing keys option

# (Optional) Cache your auth credentials for 6 hours
git config --global credential.helper 'cache --timeout=21600'
```
