# First-run setup

Only a coordinator runs this, at "Coordinator start", when
`lease.py config show --project-root "$PWD"` exits 3. The output's
`unconfigured` list names the missing scopes: `machine`, `project` or both.
A member never asks: it uses the existing config or the built-in defaults and
tells its coordinator that the project is not configured. Ask again only when
the user asks to reconfigure.

| Scope | File | Reused | Settings |
| --- | --- | --- | --- |
| Machine | `$DIR/config.json` | All projects on this machine | memory reserve, disk floor, pressure gate, dashboard port, optional slot caps |
| Project | `$DIR/projects/<key>.json` | All worktrees of one repository | base branch, merge method, leases default, per class: max lease minutes, peak mode, starting GiB |

Nothing is written into the repository.

Claude uses `AskUserQuestion` for the question groups below. Codex uses
`functions.request_user_input_async` when available, or
`functions.request_user_input` only when allowed by the current mode and tool
instructions; split groups to fit the tool's question limit. Ordinary chat is
the fallback. Wait for required choices before writing their configuration.

## 1. Detect

Run these first, and put the real numbers into the options:

```bash
sysctl -n hw.memsize hw.ncpu
df -g /
gh repo view --json defaultBranchRef,squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
```

## 2. Machine questions (only when `machine` is unconfigured)

Ask these four questions using the agent's question tool. Put the recommended option
first and add "(Recommended)" to its label.

1. **Memory reserve** (header "RAM floor"): GiB kept free for the OS, apps and
   agent sessions; leases never use it. Options: 6 GiB (Recommended for
   16-32 GiB), 4 GiB, 10 GiB. On 64 GiB or more, recommend about 10%.
2. **Disk floor** (header "Disk floor"): below this, BUILD grants stop.
   Options: 4 GiB (Recommended), 10 GiB, 20 GiB. Show the free space you
   measured in the question.
3. **Pressure gate** (header "Host gate"): Standard: 200 swap-outs per 12 s in
   two samples, load below 2.5 × cores (Recommended). Strict: 100 and 1.5 ×
   cores. Loose: 500 and 4 × cores. Show the core count.
4. **Slot caps** (header "Slot caps"): a hard limit on top of the memory
   budget. Compute the budget (RAM − reserve) with the class peaks. When it
   fits two of any class (for example two E2E stacks) but not one of every
   class alongside it, recommend "BUILD 1, E2E 1"; otherwise recommend "No
   caps (memory budget only)". Offer "E2E 1 only" as the third option. If
   another coordinator on the machine set caps, say so in the question.

Then run:

```bash
lease.py config set-machine --reserve-gib <n> --disk-floor-gib <n> --max-swapouts <n> --swap-interval-s 12 --load-per-core <k> --dashboard-port 4720 [--max-slots BUILD=1 --max-slots E2E=1]
```

If the user names other shared actions (one browser window, a test database, a
tunnel), add each with `lease.py config set-class` (`references/leases.md`).

## 3. Project questions (only when `project` is unconfigured)

Ask these four questions using the agent's question tool:

1. **Memory peaks** (header "Peaks"): Learn: start at BUILD 10 GiB and E2E
   8 GiB, then measure each lease with `lease.py measure-peak` (Recommended).
   Fixed at those values. Learn from smaller starting values (BUILD 6, E2E 4):
   the class default is a floor until three samples exist, so a low start
   admits more early on.
2. **Lease time limits** (header "Max time"): Learn from recorded runs, capped
   at BUILD 20 / E2E 45 min (Recommended). Fixed at 20 and 45. Fixed short: 10
   and 30. Fixed long: 30 and 60. Longer runs are split. Learn mode sets the
   limit to p90 of the last 10 runs + 25% (at least 5 min), never above the cap.
3. **Merge setup** (header "Merging"): the detected default branch with the
   allowed merge method (Recommended), for example "main + squash
   (detected)". When the repository uses a merge queue or a required default
   method, offer "main + merge queue / repository default" (`auto`). Add the
   other allowed methods as options.
4. **Leases in this project** (header "Leases"): Off until the host swaps
   (Recommended), or On from the start.

Then run, one call per class for class settings:

```bash
lease.py config set-project --root "$PWD" --name "<repo>" --base-branch <b> --merge-method <m> --leases-default <on|off>
lease.py config set-project --root "$PWD" --class BUILD --max-minutes <n> --minutes <learn|fixed> --peak <learn|fixed> --default-gib <n>
lease.py config set-project --root "$PWD" --class E2E --max-minutes <n> --minutes <learn|fixed> --peak <learn|fixed> --default-gib <n>
```

## 4. Confirm

Run `lease.py config show --project-root "$PWD"` (exit 0), `note` the chosen
values in the ledger, and tell the user in one line. With learn mode, start
`lease.py measure-peak` after every grant (`references/leases.md`); without samples,
learn mode stays at the starting values.

## Using the values

- Lease limits: split a request longer than `maxMinutesEffective` from
  `lease.py config show --project-root <worktree>`.
- Merging: use `baseBranch` where the stack steps say `main`. Run
  `gh pr merge --auto --<mergeMethod>`; for `auto`, run `gh pr merge --auto`
  with no method flag (the merge queue or the repository default applies).
- Leases default: at coordinator start, when no coordinator has set leases
  and the project says `on`, ask the user before you run `lease.py leases on`.
- Disk: when `lease.py host-check` prints `disk_low=yes`, stop BUILD grants and
  propose removing unused worktrees.
