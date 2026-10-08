# Lessons from earlier runs

Each item is a failure pattern seen before. The fix is in the skill; this file
explains why. Lessons that hold only for one machine or project go into
`lease.py memory`, not here.

## Stacks

- **Parallel fixes across a stack.** Fixing many stacked PRs at once caused
  cascade merges, agents that stopped mid-merge and noisy Auto-fix events.
  Fix: one active PR per stack, others paused with Auto-fix off.
- **Stacked PR merged into its parent.** It folded its commits into the parent
  PR and skipped its own review and CI. Fix: merge each PR into main, then
  retarget the next.
- **Rebase after the bottom merged.** It rewrote history under open review
  threads. Fix: merge main into the branch.
- **Auto-merge reported as merged.** "Auto-merge on" was reported as done, and
  the PR then sat blocked. Fix: report the exact state; finish only
  on MERGED with a SHA.
- **Peer instruction ignored.** A member held its PR because its first prompt
  said "do not open a PR until asked", and the PR rule came only through the
  coordinator. Fix: the welcome message states that directions count as the
  user's, inside the member limits.

## Coordination

- **Session restart.** After a context reset, the Monitors and the dashboard
  server were gone and an expired lease held its slot. Fix: on
  resume, read the roster and ledger, re-arm Monitors, restart the server
  (a no-op when it runs) before anything else.
- **Wrong number to a peer.** A figure sent to another coordinator was
  retyped from memory and wrong. Copy numbers from command output; correct
  mistakes at once.
- **Messaging cap.** Messaging a session by id stopped after a run of
  messages until the user typed in that session. Use the name route.
- **Static dashboard.** A dashboard file opened in an editor side panel never
  updated. Serve it over localhost; the page updates by SSE.

## Leases

- **Grant on a busy host.** The swap check and `acquire` ran in one command,
  and the grant went through while the host swapped heavily. Fix: check, read,
  then acquire.
  To undo, release and re-queue with `--front`.
- **Fixed second slot.** A second concurrent build admitted on a healthy
  free-memory reading drove the host into swap within minutes and hung a
  stack. A one-off memory reading does not predict a build's peak. Fix: admission by measured
  per-class peaks against a memory budget, plus the swap check.
- **Missed expiry.** No one released an expired lease and the queue stalled. Fix: the expiry Monitor and a check in every heartbeat round.
- **Kill request.** Asking the user to kill a stopped member's processes was
  refused. Ask the holder first, then report to the user.
- **Over-strict gate.** "Abort on any swap-out increase" aborted runs on
  harmless noise. Use a threshold over two samples.
- **Local rules in generic text.** Rules and figures from one repository or
  one machine went into the skill text and applied everywhere. Fix: project
  and machine rules and lessons go into `lease.py memory`.
