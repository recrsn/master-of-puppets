# master-of-puppets

Agent skills for coordinating many local coding-agent sessions (Claude Code and
Codex) on one machine.

## Skills

### `master-of-puppets`

A coordinator session takes PR stacks to merged (running multiple coordinators
at once is supported as an advanced path). The coordinator:

- watches inboxes, lease expiry and PR state with Monitors, and runs a status
  heartbeat round on a schedule that checks on members who forget to report;
- moves each stack bottom-up: one active PR, retarget to the base branch after
  the PR below merges, auto-merge, confirm the merge SHA;
- records members, tasks and decisions in a shared roster and ledger;
- optionally grants machine-wide leases for shared actions (builds, local
  stacks, a single browser window, a test database). Members size each run
  (minutes, memory, cores); the coordinator grants against memory and core
  budgets, refuses requests below their measured peaks, and checks swap, load
  and disk;
- gives tasks and lease queue entries a priority: all start at 0, the user's
  urgent work goes first, and the coordinator pushes back its own sweeps and
  scheduled runs while regular tasks wait;
- serves one live dashboard: CPU, memory, swap and disk meters, what needs
  you first, one board of all tasks grouped by stream and state, and lease
  lanes, updated over SSE.

### `puppet`

A working session joins a coordinator as a member. It reports by message
(JOIN, UPDATE, TASK REQUEST, IDLE, LEAVE), follows ACTIVE and PAUSE directions,
queues its own lease requests with `puppet.py request`, waits with
`puppet.py await-grant`, asks for more time with `puppet.py extend`,
releases its own leases, and takes its own PRs to
merged. Only a coordinator grants and extends. The coordinator records membership and
decisions.

### `scout`

A read-only session joins a coordinator to watch one target (production
signals, a release, the host and credentials, PRs, security, or member
compliance). It records its ticks and open alerts in its own watch state via
`puppet.py scout` and sends ALERT, UPDATE, GAP and DONE to its coordinator.
Scouts never implement, hold leases or open PRs.

Four files in `master-of-puppets/scripts` do the work: `coordinator.py`
(roster, members, leases, messaging, shared-record reads, watchers, config and
install), `puppet.py` (the commands a member or scout runs: roster, host,
route, tell, memory, the shared-record reads, lease request, wait, extension
request, release, and scout state), `moplib.py`
(the state code both share) and `server.py` (dashboard, with the page shell
`dashboard.html`). All use only the Python standard library.

## Requirements

- macOS (host metrics use `vm_stat`, `sysctl`, `memory_pressure`, `top` and `lsof`)
- Python 3.10 or later
- GitHub CLI (`gh`), authenticated, for PR state and stack moves
- Claude Code or Codex (CLI or Desktop); use the routes available in your agent

## Install

With the [`skills` CLI](https://github.com/vercel-labs/skills), user-wide for
Claude Code and Codex:

```bash
npx skills add recrsn/master-of-puppets --skill master-of-puppets --skill puppet --skill scout -g -a claude-code -a codex
```

Install all three (or at least `master-of-puppets` alongside `puppet` or
`scout`, since `puppet` and `scout` link into `../master-of-puppets/references/`):
the coordinator uses `master-of-puppets`, working sessions use `puppet`, and
read-only watchers use `scout`.
Drop `-g` to install into the current project instead (`.claude/skills/` and
`.agents/skills/`). Update or remove them later:

```bash
npx skills update -g
```

```bash
npx skills remove --global --skill master-of-puppets --skill puppet --skill scout
```

From a local clone, link the skills instead so edits apply at once:

```bash
ln -s "$PWD/skills/master-of-puppets" ~/.claude/skills/master-of-puppets
```

```bash
ln -s "$PWD/skills/puppet" ~/.claude/skills/puppet
```

```bash
ln -s "$PWD/skills/scout" ~/.claude/skills/scout
```

Shared state lives in `$MACHINE_LEASE_DIR` (default
`~/.local/state/machine-leases`). The coordinator installs `moplib.py`,
`coordinator.py` and `puppet.py` there with
`python3 -I skills/master-of-puppets/scripts/coordinator.py install` and
asks you for machine and project defaults. Every session runs these live
copies, so all sessions use one version against the shared state. When the
skill copy changes, the helpers warn that an update is due; on your word,
`install` updates the live copies.

## Use

- In the session that should coordinate: `/master-of-puppets`, then describe
  the work or stack it owns.
- In each working session: `/puppet`. The session joins the coordinator. Tasks
  the coordinator starts open with a kickoff line that makes the new session
  run `/puppet` by itself.
- In a read-only watcher session: `/scout` (or enrolled automatically via a
  `MASTER-OF-PUPPETS SCOUT ENROLLED` kickoff line).
- Dashboard: `http://localhost:4720/`.

In Codex, invoke the skills as `$master-of-puppets`, `$puppet` and `$scout` (or
by name).
Each session first finds its host (T3 Code, Claude Desktop, the Claude Code
CLI, Codex Desktop or the Codex CLI) and reads only that host's guide in
[references/hosts/](skills/master-of-puppets/references/hosts/README.md): its
send tool, session ids, scheduler, watchers and PR binding.

See `skills/master-of-puppets/SKILL.md` for the coordinator workflow,
`skills/puppet/SKILL.md` for the member side, `skills/scout/SKILL.md` for the
scout side, and `skills/master-of-puppets/references/` for the protocol, rules,
leases, setup, dashboard and multi-coordinator details.

## Evals

`skills/*/evals/evals.json` hold dry-run scenarios. Run them
against a fixture `MACHINE_LEASE_DIR`, never the live state, and without
messaging real sessions.

## License

[CC0 1.0 Universal](LICENSE): public domain dedication.
