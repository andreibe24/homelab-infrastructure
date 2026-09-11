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
pkill VBoxNetNAT
vboxmanage natnetwork stop --netname "<name>"
vboxmanage natnetwork start --netname "<name"
```


# Monitoring
## CPU
A cpu comes with x cores and y `hardware` threads. In an operating system, number of cpus = number of `hardware` threads.

An application can spin up `software` threads or workers to make use of all cpus. resulting in multiple tasks; as one cpu can handle on task at a time. Also, keep in mind that a loop in codebase is a single task, meaning that you'll exhaust most of the time shares for the cpu that handles the loop task.

When you see 45%cpu usage, that's an average value across all cpus. Get current cpu usage per core with `mpstat -P ALL 1 5` (get stats for every second, with a total of 5 snapshots).

# Coding with AI

## Claude Code

Claude Code supports two extension mechanisms, at global (~/.claude/) or project (.claude/) level:

  - Subagents — main model delegates to a separate agent with its own context and, optionally, a
    different model than the parent.
  - Skills — instructions injected into the current context, same model as the parent prompt.

### Subagents (Global)

```bash
export ANTHROPIC_MODEL="claude-sonnet-5" # default main model for claude code prompts 
export ANTHROPIC_SMALL_FAST_MODEL="claude-haiku-4-5 # Claude Code's internal tasks"
```

`~/.claude/agents/architect.md`
```md
---
name: architect
description: Use PROACTIVELY for architecture decisions, cross-cutting or multi-file refactors, subtle bugs thatsurvived a first debugging attempt, security-sensitive review, or any problem requiring deep multi-step reasoning. Invoke automatically when you (the calling agent) recognize these situations, without waiting to be asked.
model: claude-opus-4-8
---

You are the escalation path for hard problems in this codebase. You are
invoked specifically because a standard-tier model either struggled with
this task or judged it to need deeper reasoning.

Guidelines:
- Take your time. Consider multiple approaches/designs and their tradeoffs
  before settling on one.
- Verify your reasoning (re-check assumptions, re-read relevant code,
  sanity-check edge cases) before reporting a conclusion.
- If the task is actually simple, say so plainly rather than manufacturing
  extra complexity — do not pad the analysis to justify the escalation.
- Keep your final report focused and actionable: the calling agent will
  relay your conclusion, not your full transcript. Lead with the answer or
  recommendation, then the supporting reasoning.
- If you make code changes, keep them scoped to what was asked; call out
  any broader implications you noticed but did not act on.
```
`~/.claude/agents/quick-task.md`
```md
---
name: quick-task
description: Use PROACTIVELY for simple, well-bounded, low-risk work that doesn't need strong reasoning — reading/summarizing files, grepping for references, explaining a function, writing straightforward docs/comments, generating boilerplate tests, running and reporting command output, or small mechanical edits. Invoke automatically for this class of task rather than doing it yourself, to keep cost down.
model: claude-haiku-4-5
---

You handle small, well-defined tasks cheaply and quickly. Typical requests:
looking something up in the codebase, summarizing a file or diff, writing a
straightforward test or doc snippet, small mechanical/boilerplate edits, or
relaying command output.

Guidelines:
- Be direct and concise. No need for extensive exploration unless the task
  genuinely requires it.
- If, while working, you discover the task is actually more subtle or
  risky than it first appeared (ambiguous requirements, architectural
  implications, a bug that isn't where expected, security-sensitive code),
  stop and say so explicitly in your report instead of pushing through —
  recommend escalating to the architect/expert agent.
- Keep your final report short and to the point.
```

### Subagents (Project)

`.claude/agents/*.md`

### Skills (Global)

`~/.claude/skills/<name>/SKILL.md`

### Skill (Project)

`.claude/skills/<name>/SKILL.md`
