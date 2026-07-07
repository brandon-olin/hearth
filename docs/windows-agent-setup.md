# Windows Gaming PC — Autonomous Agent Environment Setup

Roadmap for running long (~4 hr) unattended Claude Code sessions against Hearth on the Windows desktop, keeping it fully separate from the day-job MacBook.

**Verified against official docs (July 2026):** [Setup](https://code.claude.com/docs/en/setup) · [/goal](https://code.claude.com/docs/en/goal) · [Routines](https://code.claude.com/docs/en/routines) · [Getting started with loops](https://claude.com/blog/getting-started-with-loops)

## Corrections to the Grok thread

Its advice was directionally right but generic. What it missed:

- **You don't need LangGraph/CrewAI or custom loop scripts.** Claude Code now ships the loop primitives natively: `/goal` (run until a verifiable condition holds), `/loop` (re-run on an interval), `/schedule` (cloud routines that run with your PC off), auto mode (no per-tool permission prompts), and dynamic workflows. Your use case is exactly what `/goal` + auto mode was built for.
- **WSL 2 isn't just "nicer" — it's required for sandboxing.** Claude Code's OS-level sandbox is supported on WSL 2 and *not* on native Windows. For unattended runs, sandboxing is what lets you safely leave auto mode on. This settles the WSL-vs-native question.
- **Prefer the native installer, not npm.** `curl -fsSL https://claude.ai/install.sh | bash` (inside WSL). It auto-updates; npm install is a fallback.
- **You already have the harness.** `agent/coding.md`, `agent/initializer.md`, `init.sh`, `feature_list.json`, and `claude-progress.txt` are precisely the "planning files + session protocol" pattern the loops article describes. The work here is porting your environment, not designing a workflow.

---

## Phase 1 — WSL 2 + toolchain (~1 evening)

1. PowerShell (admin): `wsl --install` → reboot → set up Ubuntu user.
2. Install **Windows Terminal** (Microsoft Store) as your host terminal.
3. Inside Ubuntu, install the stack Hearth needs:
   ```bash
   sudo apt update && sudo apt install -y git build-essential python3.12 python3.12-venv postgresql postgresql-contrib
   # Node 22+ via nvm
   curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
   nvm install 22
   ```
4. Start Postgres and create the dev database/user to match your `.env`:
   ```bash
   sudo service postgresql start
   sudo -u postgres createuser -s $USER && createdb hearth
   ```
   Add `sudo service postgresql start` to `~/.bashrc` or enable systemd in `/etc/wsl.conf` (`[boot] systemd=true`) so it survives WSL restarts.
5. New SSH key for GitHub (`ssh-keygen -t ed25519`), add to GitHub. Keep this machine's key separate from the Mac's.
6. **Keep the repo inside the WSL filesystem** (`~/code/hearth`), not `/mnt/c/...` — `/mnt/c` I/O is dramatically slower and causes file-watcher issues with Next.js dev servers.

## Phase 2 — Claude Code install + config (~30 min)

1. Inside WSL: `curl -fsSL https://claude.ai/install.sh | bash`
2. `claude` → log in with your **personal** claude.ai account (Pro/Max required). Clean separation: no work credentials on this machine.
3. `claude doctor` to verify.
4. Clone and bring up Hearth:
   ```bash
   git clone git@github.com:brandon-olin/hearth.git ~/code/hearth
   cd ~/code/hearth && ./init.sh
   ```
   Copy `.env` values over manually (don't commit; Vercel/Neon keys stay in their platforms — for local runs you only need the dev-DB URL and any local secrets).
5. Open the folder in Claude Code once interactively and accept the workspace trust dialog (required for `/goal`, which rides the hooks system).
6. Enable sandboxing + configure auto mode in `.claude/settings.json` so unattended turns don't stall on permission prompts. Start conservative: allow file edits, `git commit`, test/build commands; deny `git push`, `rm -rf`, network beyond what dev servers need. Loosen as trust builds.

## Phase 3 — Supervised shakedown (~2–3 evenings)

Goal: confirm the harness behaves on this machine before leaving it alone.

1. Run one small feature from `feature_list.json` fully interactively (turn-based loop) — verifies Postgres, migrations, ports 1337/1339, `init.sh` all work under WSL.
2. Add a **verification skill** (`.claude/skills/verify-hearth-change/SKILL.md`) encoding your definition of done, including the endpoint smoke-test rule: *execute* (not just register) every new endpoint, `npx tsc --noEmit` clean, api tests pass, migrations applied. The loops article's core lesson: loop quality = quality of self-verification.
3. First `/goal` run, watched:
   ```
   /goal Implement feature <id> from feature_list.json following agent/coding.md.
   Done when: every verification step listed for the feature has been executed and passes,
   npx tsc --noEmit is clean, api tests pass, a new session block is appended to
   claude-progress.txt, and all changes are committed. Stop after 25 turns.
   ```
   Note the condition is *evaluable from the transcript* — the evaluator model only sees what Claude surfaces, so the goal must name the checks to run.

## Phase 4 — The 4-hour morning run (steady state)

Morning ritual (~5 min before day job):

1. Pick/refine the target feature in Cowork the night before (your existing `feature_list.json` + `claude-progress.txt` planning flow — unchanged).
2. On the gaming PC:
   ```bash
   tmux new -s hearth   # session survives closing the terminal
   cd ~/code/hearth && claude
   ```
3. Set the goal (template above), with auto mode on. Add a time bound: "or stop after 4 hours."
4. Walk away. At lunch: `tmux attach -t hearth`, run `/goal` (no args) for turns/token spend, review the diff, `/code-review` with a fresh agent if it's substantial, then push.

Guardrails that make this safe:

- **Work on a branch.** Add "create and stay on a `feature/<id>` branch; never push" to the goal or `agent/coding.md`. You merge at lunch.
- **One feature per run** — already your harness's rule; it maps 1:1 to one `/goal`.
- **Turn cap + time cap in every condition.** A stuck loop burns tokens; caps bound the blast radius.
- **Windows power settings:** disable sleep while plugged in (Settings → Power), or the run dies mid-morning. Gaming PCs default to aggressive sleep less often, but check.
- **Token budget:** `/usage` breaks down spend; `/goal` status shows per-goal tokens. Calibrate after the first few runs before going bigger.

## Phase 5 — Optional escalations (later)

- **Cloud routines (`/schedule`)** — run while the PC is *off*, on Anthropic infra, cloned from GitHub. Natural fit once deploy-001 lands (Vercel/Railway/Neon) since routines work against the repo, not your local Postgres. E.g., nightly: triage new issues, or "port yesterday's merged PRs into docs." Also the replacement/upgrade path for the Telegram-bot `/run` flow.
- **`/loop` for external-state work** — e.g. `/loop 15m check PR #N, address review comments, fix failing CI` after you open a PR at lunch.
- **Dynamic workflows** — parallel worktree exploration with an adversarial judge; overkill until single-goal runs feel routine.
- **Second machine access:** Remote Control or `tmux` over Tailscale lets you peek at the run from the Mac at lunch without touching work separation (viewing personal project ≠ mixing environments).

## Success criteria

- [ ] `claude doctor` clean inside WSL 2, sandboxing enabled
- [ ] `./init.sh` green: API on 1339, web on 1337, migrations applied
- [ ] One feature completed via supervised `/goal` run, verification skill fired
- [ ] One unattended 4-hour run completed with committed, reviewable branch and updated `claude-progress.txt` / `feature_list.json`
