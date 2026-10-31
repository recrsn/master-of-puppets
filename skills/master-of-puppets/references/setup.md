# First-run setup

Only a coordinator runs this, at "Coordinator start", when
`coordinator.py config show --project-root "$PWD"` exits 3. The output's
`unconfigured` list names the missing scopes: `machine`, `project` or both.
A member never asks: it uses the existing config or the built-in defaults and
tells its coordinator that the project is not configured. Ask again only when
the user asks to reconfigure.

| Scope | File | Reused | Settings |
| --- | --- | --- | --- |
| Machine | `$DIR/config.json` | All projects on this machine | memory and core reserve, size margin, disk alarm, pressure gate, dashboard port, optional slot caps |
| Project | `$DIR/projects/<key>.json` | All worktrees of one repository | base branch, merge method, leases default, per class: learn mode (class values come from coordinator votes) |

Nothing is written into the repository. Every limit is a config number that
`coordinator.py` enforces. When the user later changes a limit, change it here
with `config set-machine`, `set-class` or `set-project` (each with an
optional `--reason`), never with `memory add`.

Ask the question groups below with the agent's question tool
(`agents.md`, "Ask setup questions"). Wait for required choices before
writing their configuration.

## 1. Detect

Run these first, and put the real numbers into the options:

```bash
sysctl -n hw.memsize hw.ncpu
df -g /
gh repo view --json defaultBranchRef,squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
```

## 2. Machine questions (only when `machine` is unconfigured)

Ask these four questions. Put the recommended option
first and add "(Recommended)" to its label.

1. **Reserve** (header "Reserve"): memory and cores kept free for the OS, apps
   and agent sessions; leases never use them. Options: 6 GiB and 2 cores
   (Recommended for 16-32 GiB), 4 GiB and 1 core, 10 GiB and 4 cores. On
   64 GiB or more, recommend about 10% of each. Show the RAM and core count.
2. **Disk alarm** (header "Disk alarm"): below the alarm level, the host check
   warns; below the floor, no lease is granted. Options: alarm 10 / floor 4 GiB
   (Recommended), 20 / 10 GiB, 6 / 2 GiB. Show the free space you measured in
   the question.
3. **Pressure gate** (header "Host gate"): Standard: 200 swap-outs per 12 s in
   two samples, load below 2.5 × cores (Recommended). Strict: 100 and 1.5 ×
   cores. Loose: 500 and 4 × cores. Show the core count.
4. **Slot caps** (header "Slot caps"): a hard limit on top of the memory and
   core budgets. Compute the budgets (RAM − reserve, cores − reserve) with the
   class peaks. When they
   fits two of any class (for example two E2E stacks) but not one of every
   class alongside it, recommend "BUILD 1, E2E 1"; otherwise recommend "No
   caps (memory budget only)". Offer "E2E 1 only" as the third option. If
   another coordinator on the machine set caps, say so in the question.

Then run:

```bash
coordinator.py config set-machine --reserve-gib <n> --reserve-cpus <n> --disk-floor-gib <n> --disk-alarm-gib <n> --max-swapouts <n> --swap-interval-s 12 --load-per-core <k> --dashboard-port 4720 [--max-slots BUILD=1 --max-slots E2E=1]
```

The size margin (`--size-margin`, default 0.25) is how far a member's request
may be below the observed peak before `acquire` refuses it. Keep the default
unless the user names another.

If the user names other shared actions (one browser window, a test database, a
tunnel), add each with `coordinator.py config set-class` (`references/leases.md`).

## 3. Project questions (only when `project` is unconfigured)

Ask these two questions. Do not ask about class peaks, cores or lease time
limits: they start at 0 (no limit), and coordinators set them from their
observations without the user (`references/leases.md`, "Class defaults by
vote").

1. **Merge setup** (header "Merging"): the detected default branch with the
   allowed merge method (Recommended), for example "main + squash
   (detected)". When the repository uses a merge queue or a required default
   method, offer "main + merge queue / repository default" (`auto`). Add the
   other allowed methods as options.
2. **Leases in this project** (header "Leases"): Off until the host swaps
   (Recommended), or On from the start.

Then run (learn mode records peaks and run times, the evidence for votes):

```bash
coordinator.py config set-project --root "$PWD" --name "<repo>" --base-branch <b> --merge-method <m> --leases-default <on|off>
coordinator.py config set-project --root "$PWD" --class BUILD --minutes learn --peak learn
coordinator.py config set-project --root "$PWD" --class E2E --minutes learn --peak learn
```

## 4. Confirm

Run `coordinator.py config show --project-root "$PWD"` (exit 0), `note` the chosen
values in the ledger, and tell the user in one line. With learn mode, start
`coordinator.py measure-peak` after every grant (`references/leases.md`); without samples,
learn mode stays at the starting values.

## Using the values

- Merging: use `baseBranch` where the stack steps say `main`, and
  `mergeMethod` in SKILL.md, "Driving a stack", step 2.
- Leases default: at coordinator start, when no coordinator has set leases
  and the project says `on`, ask the user before you run `coordinator.py leases on`.
- Lease limits and the disk alarm: `references/leases.md`.
