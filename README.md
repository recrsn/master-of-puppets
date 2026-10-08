# master-of-puppets

Agent skills for coordinating many local coding-agent sessions (Claude Code and
Codex) on one machine.

## Skills

### `master-of-puppets`

One or more coordinator sessions take PR stacks to merged. Coordinators:

- watch inboxes, lease expiry and PR state with Monitors, and run a status
  heartbeat round on a schedule that checks on members who forget to report;
- move each stack bottom-up: one active PR, retarget to the base branch after
  the PR below merges, auto-merge, confirm the merge SHA;
- record members, tasks and decisions in a shared roster and ledger;
- optionally grant machine-wide leases for shared actions (builds, local
  stacks, a single browser window, a test database). Capacity adapts to
  measured memory peaks and run times, with swap, load and disk checks;
- share one live dashboard: an at-a-glance strip with CPU, memory, swap, disk,
  leases and coordinators, updated over SSE.

### `puppet`

A working session joins a coordinator as a member. It sends messages only
(JOIN, UPDATE, LEASE REQUEST, ENROLL REQUEST, LEAVE), follows ACTIVE and PAUSE
directions, waits for leases with `lease.py await-grant`, and takes its own
PRs to merged. The coordinator records everything.

Two files in `master-of-puppets` do the work: `scripts/lease.py` (state, leases, messaging, waiters,
watchers) and `scripts/server.py` (dashboard). Both use only the Python
standard library.

## Requirements

- macOS (host metrics use `vm_stat`, `sysctl`, `memory_pressure`, `top` and `lsof`)
- Python 3.10 or later
- GitHub CLI (`gh`), authenticated, for PR state and stack moves
- Claude Code; Codex is optional

## Install

With the [`skills` CLI](https://github.com/vercel-labs/skills), user-wide for
Claude Code and Codex:

```bash
npx skills add recrsn/master-of-puppets --skill master-of-puppets --skill puppet -g -a claude-code -a codex
```

Install both: coordinators use `master-of-puppets`, members use `puppet`.
Drop `-g` to install into the current project instead (`.claude/skills/` and
`.agents/skills/`). Update or remove them later:

```bash
npx skills update -g
```

```bash
npx skills remove --global --skill master-of-puppets --skill puppet
```

From a local clone, link the skills instead so edits apply at once:

```bash
ln -s "$PWD/skills/master-of-puppets" ~/.claude/skills/master-of-puppets
```

```bash
ln -s "$PWD/skills/puppet" ~/.claude/skills/puppet
```

Shared state lives in `$MACHINE_LEASE_DIR` (default
`~/.local/state/machine-leases`). The first coordinator installs `lease.py`
there with `python3 -I skills/master-of-puppets/scripts/lease.py install` and
asks you for machine and project defaults.

## Use

- In the session that should coordinate: `/master-of-puppets`, then name the
  stack it owns.
- In each working session: `/puppet`. The session joins the coordinator that
  owns its PRs. Tasks a coordinator starts open with a kickoff line that makes
  the new session run `/puppet` by itself.
- Dashboard: `http://localhost:4720/`.

See `skills/master-of-puppets/SKILL.md` for the coordinator workflow,
`skills/puppet/SKILL.md` for the member side, and
`skills/master-of-puppets/references/` for the protocol, rules, leases, setup
and dashboard details.

## Evals

`skills/*/evals/evals.json` hold dry-run scenarios. Run them
against a fixture `MACHINE_LEASE_DIR`, never the live state, and without
messaging real sessions.

## License

[CC0 1.0 Universal](LICENSE): public domain dedication.
