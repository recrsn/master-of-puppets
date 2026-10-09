# Dashboard

There is one dashboard per machine. Every coordinator runs
`python3 -I scripts/server.py` in the background; the first one serves, later
ones print "already serving" and exit. Give the user `http://localhost:4720/`
(or the configured `dashboardPort`).

`server.py` renders the page in memory from `leases.json`, `roster.json`,
`ledger.jsonl`, `config.json`, `projects/*.json` and
`dashboard/*-state.json`, on any change and every 30 s (ETAs, heartbeat age).
It pushes SSE `update` events, and the page swaps its body in place. Every 5 s
it samples the host and pushes a `host` event; the host meters update without a
re-render. When the server stops, "Live" in the header turns to "Offline".
A file opened in an editor side panel does not update; do not offer that.

`server.py` fills the page shell `scripts/dashboard.html` (styles and the
live-update script). It follows the system light or dark theme.

Layout, desk mode: the header shows CPU, memory, swap and disk meters, a
Desk/Wall switch and a Ledger button. "Needs you" comes first, worst first:
host alarms, expired leases, stale coordinators, decisions, blocked tasks and
members with no update for 30 min. One card per task holds all its reasons,
with a chip for its stream. Then the work board groups the other tasks by
stream (open streams in roster order, then "No stream"), and by state inside
each stream (Done is collapsed). Each stream header shows its label, owner,
open tasks, tasks under Needs you and its goal. With no streams, the board
groups by state only. The side column shows lease timelines and queues (only
when leases are on or in use), then the coordinators with their open streams,
links and notes. The Ledger button
opens the newest 20 shared-ledger entries in a drawer.

Each queued lease entry has Move up and Cancel buttons (Cancel asks first).
They run `lease.py up|unwait --notify`, which tells each affected coordinator
(`references/leases.md`); a toast shows the result and the delivery. The
server accepts these posts only from its own page.

Wall mode is the same data, large, for a shared screen: host tiles, the
"need you" count and cards, task counts by state and by stream, and the lease
timelines.
Open `http://localhost:4720/?mode=wall`; the page keeps the last mode.

## Writing for the dashboard

The user reads the dashboard in a few seconds. Every text on it must be
concise and readable. This applies to the state file, `member update`,
`decision add`, `note` (the ledger drawer) and lease `--holder` names.

| Field | Limit | Says |
| --- | --- | --- |
| stream `label` | 4 words (40 characters, enforced) | The goal's name: "Repo access security". |
| stream `goal` | 1 sentence (140 characters, enforced) | What done means for the stream. |
| task `name` | 6 words | What the task is. Not its status. |
| `phase` | 5 words | The current step: "In review", "Waiting for BUILD", "Auto-merge on". |
| `latest` | 1 sentence, 20 words | The newest fact and, if useful, the next step. |
| decision `text` | 1 question, 25 words | What the user must decide, and where (PR number). |
| `notes` | 3 per coordinator, 1 sentence each | Cross-task facts the user must know. Remove a note when it is no longer true. |
| ledger `note` | 2 sentences | What happened, the result, the next step. |
| lease `--holder` | task id + 5 words | "S9 typecheck and unit tests". |

Do:
- Use plain words, active voice and present tense.
- Write PRs as `#123` and times as `14:05Z`, only when they help.
- Replace `latest`; do not add to it. It holds only the newest fact.
- Put detail behind a link (PR, report file, session), not in the text.

Do not:
- Write full commit SHAs (use 7 characters, only when the user needs it),
  test counts, file paths, command lines, lease or queue IDs, or stack traces.
- Repeat the phase, the task name or the time in `latest`; the dashboard
  already shows them. No "STATUS 18:35Z:" prefixes.
- Write lists of steps, internal reasoning or your tool's process.

Example:

- Too long: "B1 from main 54c56d84eca: bot-contracts queue-pause contract;
  agent-platform store/control/workflow/routes behind
  ENABLE_CODING_QUEUE_PAUSE_ON_STOP (off); Handler client/router +
  resumeQueuedMessages boundary + authz entry. Edit-only subagents; one BUILD
  request next."
- Good: phase "Editing B1", latest "Queue pause on Stop is behind a flag (off).
  Next: one BUILD run."

When a member's UPDATE is long, shorten it before `member update`. Keep the
full text in your own notes if you need it.

## Your state file

`$MACHINE_LEASE_DIR/dashboard/<slug>-state.json`. `lease.py member add|update|remove`,
`enroll` and `decision add|clear` keep its `tasks` and `decisions` current; edit
the other fields (notes, links, coordinator) by hand. The file name is your
coordinator slug; it labels your section and your decisions.

```json
{
  "updated": "12:05Z",
  "coordinator": {"label": "<slug> session", "href": "claude://claude.ai/epitaxy/<sessionId>"},
  "decisions": [{"task": "S2", "text": "Accept #123 without a local E2E?"}],
  "notes": ["#124 and the billing stack both touch the settings schema; billing goes first."],
  "links": [{"label": "Notes", "href": "file:///path/to/scratch.md"}],
  "tasks": [
    {
      "id": "S9",
      "name": "Short task name",
      "phase": "Active · auto-merge on",
      "stream": "repo-access",
      "kind": "ok",
      "latest": "One line: newest fact, with PR number.",
      "session": "claude://claude.ai/epitaxy/<sessionId>",
      "worktree": "/abs/path/to/worktree",
      "links": [{"label": "PR #123", "href": "https://github.com/<owner>/<repo>/pull/123"}],
      "eta": "optional free text when no lease entry exists"
    }
  ]
}
```

- `stream` is a stream slug from `lease.py stream add`. `enroll` and
  `member add|update --stream` set it; the roster's member entry has it too.
  Streams live in `roster.json` under `streams`, not in this file.
- `kind` sets the work group: `warn` (Blocked, also listed under Needs you),
  `work` (In progress), `ok` (On track), `done` (Done).
- A decision may be a string `"S2: text"`; the task id before the colon
  becomes a jump link to that task's session.
- A task row's lease ETA matches lease holder names against the task id,
  so start each lease `--holder` with the task id (for example `"S9 build"`).
- For Claude `session` deep links, use the session id that `ListAgents` shows for
  that session (Claude Desktop ids look like `local_...`). The
  `$CLAUDE_CODE_SESSION_ID` a member gives in its JOIN message identifies it in the
  roster; it may not open as a deep link.
- For Codex, use `codex://threads/<threadId>` for both `coordinator.href` and
  a task's `session`. Use the thread ID returned by `list_threads` or exported
  as `$CODEX_THREAD_ID`, not a subagent ID. The JSON above shows Claude links;
  replace them for Codex sessions. Open the live dashboard with
  `mcp__codex_app__open_in_codex` using a browser target when available.
- Your focus and PRs come from the roster (`coordinate` / `heartbeat`), not
  from this file.
