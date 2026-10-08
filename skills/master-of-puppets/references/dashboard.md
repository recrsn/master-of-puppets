# Dashboard

There is one dashboard per machine. Every coordinator runs
`python3 -I scripts/server.py` in the background; the first one serves, later
ones print "already serving" and exit. Give the user `http://localhost:4720/`
(or the configured `dashboardPort`).

`server.py` renders the page in memory from `leases.json`, `roster.json`,
`ledger.jsonl`, `config.json`, `projects/*.json` and
`dashboard/*-state.json`, on any change and every 30 s (ETAs, heartbeat age).
It pushes SSE `update` events, and the page swaps its body in place. Every 5 s
it samples the host and pushes a `host` event; the host cards update without a
re-render. When the server stops, the page shows a stale banner. A file opened
in an editor side panel does not update; do not offer that.

Layout: a sticky at-a-glance strip of cards at the top (needs you, CPU,
memory, swap, disk, each lease class, each coordinator; hot cards turn amber),
then decisions, one task table per coordinator, leases and queues (only when
leases are on or in use), and the newest shared-ledger entries.

## Your state file

`$MACHINE_LEASE_DIR/dashboard/<slug>-state.json`. `lease.py member add|update|remove`,
`enroll` and `decision add|clear` keep its `tasks` and `decisions` current; edit
the other fields (cards, notes, links, coordinator) by hand. The file name is your
coordinator slug; it labels your section and your decisions.

```json
{
  "updated": "12:05Z",
  "coordinator": {"label": "<slug> session", "href": "claude://claude.ai/epitaxy/<sessionId>"},
  "cards": [{"label": "Host", "value": "Calm", "sub": "0 swap-outs/12 s · load 9 · 37 GiB free"}],
  "decisions": [{"task": "S2", "text": "Approve the new DB migration in #123."}],
  "notes": ["#124 and the billing stack both touch the settings schema; billing goes first."],
  "links": [{"label": "Notes", "href": "file:///path/to/scratch.md"}],
  "tasks": [
    {
      "id": "S9",
      "name": "Short task name",
      "phase": "Active · auto-merge on",
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

- `kind` sets the badge colour: `ok`, `work`, `warn`, `done`.
- A decision may be a string `"S2: text"`; the task id before the colon
  becomes a jump link to that task's session.
- The "Next lease ETA" column matches lease holder names against the task id,
  so start each lease `--holder` with the task id (for example `"S9 build"`).
- For `session` deep links, use the session id that `ListAgents` shows for
  that session (Claude Desktop ids look like `local_...`). The
  `$CLAUDE_CODE_SESSION_ID` a member gives in its JOIN message identifies it in the
  roster; it may not open as a deep link.
- Your focus and PRs come from the roster (`coordinate` / `heartbeat`), not
  from this file.
- Only one coordinator needs a "Host" card; the first one found is shown.
