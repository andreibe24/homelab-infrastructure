# Interactive shell - fish

*What*: Use a smarter shell.

*How*: Here is exactly how:

Install fish shell via [official docs](https://github.com/fish-shell/fish-shell#packages-for-linux).

Then set fish sh as default user's shell: `chsh -s $(which fish)`.

Lastly, configure Vscode: `Open Command Palette: Ctrl+Shift+P` -> `Type: "Terminal: Select Default Profile"` -> `Choose fish from the list`.

Also, you shoud set up automatic, live history syncing across all your open fish shells:

`~/.config/fish/config.fish`
```bash
...
function sync_history --on-event fish_preexec
    history merge
end
...
```

# Declarative Deps List via package manager

*What*: How to install linux deps from apt package manager

*How*: Here is exactly how:
```bash
sudo apt update && sudo xargs -a packages.txt apt install -y
```


# Declarative Deps List via jdx/mise

*What*: Instruct jdx/mise to make available the utilities from `$HOME/.config/mise/config.toml` to all terminal windows.

*How*: Here is how:
```bash
curl https://mise.jdx.dev/install.sh | sh

echo "eval \"\$(<home-dir>/.local/bin/mise activate bash)\"" >> ~/.bashrc
# or
echo "mise activate fish | source" >> ~/.config/fish/config.fish

mkdir -p ~/.config/mise

vim ~/.config/mise/config.toml
```


# Git Setup

## SSH Authentication

*What*: The title is clear enough.

*How*: Run these commands:
```bash
# Generate keys
ssh-keygen -t ed25519 -C "<email>" -f ~/.ssh/<key-name>

# Declare your identity
git config --global user.name "<name>"
git config --global user.email "<email>"

# Go to register the keys into the github account
## Paste that public key into GitHub → Settings → SSH and GPG keys -> Select Authentication keys option
```

Ensure generated keys are used:
```bash
# cat ~/.ssh/config
Host github.com
    IdentityFile ~/.ssh/<key-name>
    IdentitiesOnly yes
```

Test:
```bash
ssh -T git@github.com
```

Cache auth creds:
```bash
# (Optional) Cache your auth credentials for 6 hours
git config --global credential.helper 'cache --timeout=21600'
```

## Auto Commit Signing(Verified Badge)

*What*: The title is clear enough.

*How*: Run these commands:
```bash
# Generate keys
ssh-keygen -t ed25519 -C "<email>" -f ~/.ssh/<key-name>

# Tell git to sign with SSH instead of GPG
git config --global gpg.format ssh

# Point git at your existing public key
git config --global user.signingkey ~/.ssh/<key-name>.pub

# Sign all commits automatically
git config --global commit.gpgsign true

# Go to register the keys into the github account
## Paste that public key into GitHub → Settings → SSH and GPG keys -> Select Signing keys option
```

# Virtual Box
## Issue: Network issues of VM like internet or ssh connection
*Solution*: Restart VM's network config (HOT UPDATE):
```bash
kill -9 <vboxnetnatPID> # ps aux | grep VBoxNetNAT
vboxmanage natnetwork stop --netname "<name>"
vboxmanage natnetwork start --netname "<name"
```


# Monitoring
## CPU
A cpu comes with x cores and y `hardware` threads. In an operating system, number of cpus = number of `hardware` threads.

An application can spin up `software` threads or workers to make use of all cpus. resulting in multiple tasks; as one cpu can handle on task at a time. Also, keep in mind that a loop in codebase is a single task, meaning that you'll exhaust most of the time shares for the cpu that handles the loop task.

When you see 45%cpu usage, that's an average value across all cpus. Get current cpu usage per core with `mpstat -P ALL 1 5` (get stats for every second, with a total of 5 snapshots).
