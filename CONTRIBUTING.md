# Contributing to LocalPibox

LocalPibox is a personal, local-first AI devstack on
[Pi.dev](https://pi.dev). The stack is designed to be **forked and
personalized** — you are welcome to contribute directly, fork it for your own
stack, or share what works on your hardware.

There are **three ways to get involved**:

---

## 1. Contribute directly

Improve patches, add features, or fix bugs in any of the repos. Each repository
has its own scope:

| Repo | What to work on |
|---|---|
| [devstack](https://github.com/localpibox/devstack) | Container image (`Dockerfile`), `lpb` launcher (`scripts/`), entrypoints (`support/`), CI |
| [config](https://github.com/localpibox/config) | Pi settings, MCP servers, custom skills, subagents presets |
| [pi](https://github.com/localpibox/pi) | Qwen `reasoning_effort` + context-overflow patches (fork) |
| [lemonade-pi-plugin](https://github.com/localpibox/lemonade-pi-plugin) | Qwen thinking + vision support (fork) |
| [pi-subagents](https://github.com/localpibox/pi-subagents) | Centralized subagent model registry (fork) |
| [lpb-memory](https://github.com/localpibox/lpb-memory) | Persistent memory / session search extension |
| [localpibox](https://github.com/localpibox/localpibox) | Project overview & stack reference |
| [localpibox.github.io](https://github.com/localpibox/localpibox.github.io) | GitHub Pages project site |

### Process

1. Fork the repo and create a feature branch off its stable branch
   (`main` for own repos, `lpb` for forks).
2. Make focused changes. **Prefer minimal, targeted patches** over broad
   rewrites.
3. For forks, keep work as a **single squashed commit** on `lpb` so the delta
   vs upstream stays one clean patch.
4. Open a PR. Describe what changed, why, and how you tested it.

### Policy notes

- **Never hardcode model names in agent defaults** — use `model: parent` so
  agents inherit the session model. See the config repo's `agents/` templates.
- **Anthropic models are not used** in this stack; Qwen (via Lemonade) is the
  default.
- Forks carry candidate **upstream contributions**: ship a patch upstream when
  it's generally useful and not too opinionated for this stack.

## 2. Fork for your stack

1. Fork the repos you care about.
2. Clone devstack and edit `lpb.stack.env` to point at your forks (see
   [Forking & Repointing](https://github.com/localpibox/devstack#forking--repointing)).
3. Build & push your image, then run `lpb`.

You own your variant — change anything: image names, container name, branch
refs, config preset.

## 3. Feed back experiences

Share what works reliably on **your hardware with your models**. Configuration
like context-window ratios, thinking levels, and model detection depends
heavily on the actual host (CPU/APU, RAM, model size). Your findings help
everyone converge on robust local setups.

Open an issue or PR with:
- Your hardware (e.g. "Ryzen AI Max+ 395, 128 GB").
- The model + provider + Pi version.
- What worked, what overflowed, and any tuning you discovered.

---

## Reporting issues

Open an issue in the relevant repo (usually `devstack`). Include:

- What you were doing.
- Exact command(s) and output.
- Host OS, container engine (podman/docker), and stack version (from
  `VERSION` / `lpb.conf.env`).

## Code of conduct

Keep it friendly and constructive — this is a personal stack shared in public.
Respect other people's hardware, models, and workflows.
