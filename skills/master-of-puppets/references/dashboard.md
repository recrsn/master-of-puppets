# Dashboard

There is one dashboard per machine. Every coordinator runs
`python3 -I scripts/server.py` in the background; the first one serves, later
ones print "already serving" and exit. Give the user `http://localhost:4720/`
(or the configured `dashboardPort`).

`server.py` renders the pages in memory from `leases.json`, `roster.json`,
`ledger.jsonl`, `config.json`, `projects/*.json`, `memory/*.json` and
`dashboard/*-state.json`, on any change and every 30 s (ETAs, heartbeat age).
It pushes SSE `update` events on `/stream`, and each page swaps its body in
place. A Config or Rules form with unsaved edits holds its page until saved. Every 5 s
it samples the host and pushes a `host` event; the host values update without a
re-render. When the server stops, the green dot in the header turns red with
"Offline".
A file opened in an editor side panel does not update; do not offer that.

`server.py` fills the page shell `scripts/dashboard.html` (styles and the
live-update script). It follows the system light or dark theme.

Pages: Dashboard (`/`), Events (`/events`), Config (`/config`) and Rules
(`/rules`). The header on each shows CPU, memory, swap and disk values and the
page links.

Dashboard: Every item is one quiet row (a dot, a
title, the time since its last change); a click opens its detail, and open rows
stay open across live updates. "Needs you" comes first, in groups: Alarms (host
alarms, expired leases, admission holds, stale coordinators; never capped),
Decisions, Blocked, Stale (members with no update for 30 min, or not joined) and
Revisit. A group shows 8 rows, then "Show N more". One row per task holds all
its reasons; its detail shows the task id, coordinator, stream, reasons, the
question and answer buttons, the latest status, Open session and Park. Then the
Work list groups the other tasks by stream (open streams in roster order, then
"No stream"), newest change first, with Done collapsed at the end of each
stream. Each stream header shows its label, open tasks, owner, tasks under
Needs you and its goal. With no streams, Work is one list. The side column
shows the leases (only when leases are on or in use): one lane per class with
its status, then the running, queued and held entries. Needs you groups, streams
and Parked collapse; the browser keeps each collapsed group collapsed.

Events: the coordinators (live, stale, idle or general; focus, streams, links
and notes), then the newest 200 shared-ledger entries, newest first.

Config: the machine limits (`config set-machine`), each lease class
(`config set-class`, Remove class runs `config remove-class`, and New class
adds one), and each configured project whose stored root exists
(`config set-project`, one form for the project and one per class). Rules: the
machine memory and each project's memory (`memory add|update|remove`). A save
posts only the changed fields with an optional reason, and runs the command as
`--by user`. The command records the change in the ledger and tells every live
coordinator and member, as when a coordinator runs it. A project with no
stored root shows its rules read only.

Parked work (members with status paused) leaves Needs you and the work board
and is listed in the Parked section, dated parks first. A park can carry a
deadline (`parkedUntil`); after it the task returns to Needs you as
"Revisit · parked until <date>". Every member's row has a Park button (an
optional date; no date means until unparked), and parked ones have Unpark.
They run `coordinator.py park|unpark --notify`, so the coordinator gets a message
from "dashboard", as with the queue buttons.

A task or queue entry with a priority other than 0 shows it ("Priority 2");
inside each stream, higher-priority tasks come first, and each lease
queue lists entries by priority, then FIFO.

A decision with suggested answers (`decision add --option`) shows one button
per option in its Needs you row. A click asks first, then runs
`coordinator.py decision answer --notify`: the decision clears, the ledger
records the answer, and the coordinator gets a message from "dashboard" with
the answer and the question. Only the option number crosses the post; the
answer text comes from the state file. A decision without options has no
buttons.

A machine-scope decision (`decision add --scope machine`) lives in
`dashboard/machine-state.json` and shows under the name "machine". Its answer
counts for every coordinator, and every live coordinator gets the message.
`update propose` adds one for each helper update; its answer is the user's
approval or rejection that `install --replace` reads.

Each queued lease entry has Move up and Cancel buttons (Cancel asks first).
They run `coordinator.py up|unwait --notify`, which tells each affected coordinator
(`references/leases.md`); a toast shows the result and the delivery. The
server accepts these posts only from its own page.

## Writing for the dashboard

The user reads the dashboard in a few seconds. Every text on it must be
concise and readable. This applies to the state file, `member update`,
`decision add`, `note` (the Events page) and lease `--holder` names.

| Field | Limit | Says |
| --- | --- | --- |
| stream `label` | 4 words (40 characters, enforced) | The goal's name: "Repo access security". |
| stream `goal` | 1 sentence (140 characters, enforced) | What done means for the stream. |
| task `name` | 6 words | What the task is. Not its status. |
| `phase` | 5 words | The current step: "In review", "Waiting for BUILD", "Auto-merge on". |
| `latest` | 1 sentence, 20 words | The newest fact and, if useful, the next step. |
| decision `text` | 1 question, 25 words | What the user must decide, and where (PR number). |
| decision `--option` | 2 to 4 options, 5 words each (60 characters, enforced) | One answer the user can click: "Yes, merge it", "Hold until Monday". |
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

`$MACHINE_LEASE_DIR/dashboard/<slug>-state.json`. `coordinator.py member add|update|remove`,
`enroll` and `decision add|clear` keep its `tasks` and `decisions` current; edit
the other fields (notes, links, coordinator) by hand. The file name is your
coordinator slug; it labels your section and your decisions.

```json
{
  "updated": "12:05Z",
  "coordinator": {"label": "<slug> session", "href": "claude://claude.ai/epitaxy/<sessionId>"},
  "decisions": [{"id": "1f3a9c2e", "task": "S2", "text": "Accept #123 without a local E2E?",
                 "options": ["Yes, merge it", "No, run E2E first"]}],
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

- `stream` is a stream slug from `coordinator.py stream add`. `enroll` and
  `member add|update --stream` set it; the roster's member entry has it too.
  Streams live in `roster.json` under `streams`, not in this file.
- `kind` sets the work group: `warn` (Blocked, also listed under Needs you),
  `work` (In progress), `ok` (On track), `done` (Done).
- A decision may be a string `"S2: text"`; the task id before the colon
  becomes a jump link to that task's session. Option buttons need the `id`
  that `decision add` writes, so add decisions with options through
  `decision add`, not by hand.
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
