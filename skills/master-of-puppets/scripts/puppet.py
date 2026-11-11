#!/usr/bin/env python3
"""Member ("puppet") commands for master-of-puppets. A member reads the roster and
the skill's memory, queues its own lease request, waits for the grant, asks for more
time and releases its own lease. Only a coordinator grants (coordinator.py acquire) and
extends (coordinator.py extend). A member never
writes the roster, ledger, dashboard or shared inbox; it messages its coordinator,
which records everything with coordinator.py. Shared code is in moplib.py.

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases).

Usage: python3 -I puppet.py <command> ...

  roster | whoami --session-id ID
       coordinators (with live: heartbeat newer than 40 minutes), members and streams
  memory list [--project-root P] [--json]      machine rules and notes, then the project's
  inbox | ledger | events | who     the shared records, read-only (coordinator.py has the
       same commands and flags); for example events --id ID shows a lease's grant and release
  sizes --worktree P [--class CLASS]
       the project's recorded run minutes, peak GiB and peak cores per class, the figures
       your coordinator charges and checks against, and the size margin: size from these
  request CLASS --coordinator C --name NAME [--id ID] --minutes N --commands TEXT --worktree P
          [--prefer KEY=VALUE ...] [--resource NAME]   (pool classes)
          [--gib N] [--cpus N] [--what TEXT]
       queue your own lease request; prints its position. You size the run: --minutes always,
       --gib and --cpus (peak memory and cores) when you know them; your coordinator charges
       its own figure for a size you leave out. The ID must start with C-q-NAME-;
       without --id, the next free C-q-NAME-<n> is used and printed first as ID <id>.
       NAME must be a member of C. The entry takes your task's priority; only your
       coordinator or the user changes it. A repeat with the same ID changes the given fields.
       Prints a warning when --gib or --cpus is below the observed peak by more than the
       size margin: your coordinator then refuses the grant unless you tell it why.
       exit 0 queued, 2 over the class limit or the whole budget (split the run), 3 refused: leases off, not a
       member of C, a foreign ID, or the ID is already held
  await-grant [CLASS] --id ID [--timeout-min N] [--appear-timeout S]   (CLASS: default the one with ID)
       prints HELD <reason> while your coordinator holds or reviews the entry (keep waiting),
       ASSIGNING <what> while a pool class creates or starts your resource (can take minutes),
       and after GRANTED of a pool class, RESOURCE <name> <info JSON>: the resource you hold
       until you release it (release never stops it: the server's pool upkeep does, when idle),
       then one final line: GRANTED, DENIED, LEFT-QUEUE, TIMEOUT or NEVER-QUEUED <reason>. Only GRANTED
       is a grant, and no other final line contains the word GRANTED. When the class has a recycle command,
       a granted resource is reset first: RECYCLING <name>, then RECYCLED. A failed reset prints
       RECYCLE-FAILED (the resource is destroyed); an unreachable one RECYCLE-UNREACHABLE (it is kept,
       marked failed). Either way you do not get it: the entry is queued again at the front
       (REQUEUED; keep waiting), up to 3 times, then LEFT-QUEUE. Exit 0 GRANTED (the only grant);
       4 DENIED by your coordinator (do not retry; ask why); 3 LEFT-QUEUE (left the queue, or every reset
       failed); 5 TIMEOUT after --timeout-min, still queued or not queued yet (run await-grant again);
       6 NEVER-QUEUED within --appear-timeout (default 600 s). Check the exit code of the bare command:
       a pipe (| tail, | tee) returns the exit code of its last command, not of await-grant
  extend [CLASS] --coordinator C --name NAME --id ID --minutes N --reason TEXT
       ask your coordinator to extend your own granted lease to expire N minutes from now.
       It does not change the expiry: the coordinator decides. Writes one event line,
         extend-request CLASS ID N min by=NAME coordinator=C reason="TEXT"
       and puts an EXTEND message in your coordinator's inbox. The coordinator
       replies LEASE EXTENDED or tells you to release.
       exit 0 asked, 2 the lease would run longer than the class limit (release it and
       request the rest), 3 refused: not a member of C, not your lease, or not held
  release [CLASS] --id ID --result pass|fail|partial [--note TEXT] [--peak-gib N] [--peak-cpus N]
          [--port N ...] [--process PATTERN ...] [--ignore-pid PID ...]
       release your own lease, never another's; records its run minutes and peaks, then
       counts what the run left in the lease's worktree (agent session processes, bare
       shells, processes that started before the grant and each --ignore-pid do not count;
       name why in --note) and writes one event line:
         release CLASS ID ran N min peak N GiB N cores result=R drained=N coordinator=C note="TEXT"
       That line is the record of the release: coordinators read it with `events`.
       When the class has a recycle command, release then resets the resource (it stays busy until
       done) and logs `resource recycled ... free=N GiB`; a failed reset destroys it with the class's
       delete command and logs `resource destroyed ... reason="..."`.
  scout tick|alert|resolve|paused|show --coordinator C --name NAME ...   (scouts only)
       a scout's own watch state file, scouts/NAME.json, which C's heartbeat and the dashboard read.
       tick [--summary TEXT]: a check (QUIET ticks and the daily summary go here, never in a message).
       alert --fingerprint F --severity P0|P1|P2 [--kind alert|gap] --text TEXT: prints NEW or
       ESCALATED (send it) or SEEN (do not send it again). resolve --fingerprint F: prints RESOLVED
       (send UPDATE recovered). paused [--clear]: a send returned Paused. Never a secret in TEXT.
       A scout holds no leases: request refuses it (exit 3)
"""
import argparse
import datetime as dt
import json
import re
import time
import os
import sys

# python3 -I keeps the script's own directory off sys.path; moplib is its sibling.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True  # no __pycache__ in the shared state dir
from moplib import (
    forward, nap,
    LOG, PEAKS, SAMPLES_KEPT, MINUTES_KEPT, load_machine, registry, class_names,
    load_project, save_project, project_key, undersized, now, lock, unlock, log, say,
    load, save, load_roster, queue_entry, extension_refusal, READS, add_read_commands, read_cmd, version_warning, drain,
    find_resource, set_state, mark_failed, parse_prefer, RESOURCE_NAME, pool_spec,
    begin_op, recycle_run, recycle_note, destroy_recycled, recycle_released, health_released,
    write_json, scout_path, scout_state, SCOUT_SEVERITIES,
)

MAX_RECYCLE_DESTROYS = 3  # resources one await-grant may destroy for failed recycles before it stops re-queueing


# ---------------------------------------------------------------- leases


def class_of(lease_id):
    """The class whose queue or holders have lease_id, else None."""
    state = load()
    return next((c for c in class_names() if any(x["id"] == lease_id for x in state[c] + state["queue"][c])), None)


def next_id(prefix, state):
    """prefix + the next n: one more than every n of prefix in the state and the events log."""
    pat = re.compile(re.escape(prefix) + r"(\d+)\b")
    seen = [0]
    for c in class_names():
        seen += [int(m.group(1)) for x in state[c] + state["queue"][c] for m in [pat.fullmatch(x["id"])] if m]
    try:
        with open(LOG) as f:
            seen += [int(n) for n in pat.findall(f.read())]
    except OSError:
        pass
    return f"{prefix}{max(seen) + 1}"


def request(args):
    """Queue the member's own entry. The member cannot grant, set a priority or jump the
    queue; its coordinator gets a REQUEST message in its inbox and grants."""
    lock()
    try:
        roster, state, machine = load_roster(), load(), load_machine()
        if roster["leases"] != "on":
            print("leases are off; run the commands without a lease")
            return 3
        me = next((m for m in roster["members"].get(args.coordinator, []) if m["name"] == args.name), None)
        if me and me.get("role") == "scout":
            print(f"{args.name} is a scout: scouts hold no leases. Send {args.coordinator} a TASK REQUEST for work that needs one")
            return 3
        if me is None:
            print(f"{args.name} is not a member of {args.coordinator}. Send it your JOIN line by its direct route "
                  "(puppet skill, section 2: JOIN — name — tool id — worktree — task — PRs — phase — commands — parent), "
                  "wait for WELCOME, then request again")
            return 3
        prefix = f"{args.coordinator}-q-{args.name}-"
        if not args.id:
            args.id = next_id(prefix, state)
            print(f"ID {args.id}")
        if not args.id.startswith(prefix):
            print(f"{args.id} is not yours; use an ID that starts with {prefix}")
            return 3
        if any(h["id"] == args.id for h in state[args.cls]):
            print(f"{args.id} is already held; release it or use a new ID")
            return 3
        try:
            prefer = parse_prefer(args.prefer)
        except ValueError as e:
            print(e)
            return 2
        if args.resource and not RESOURCE_NAME.match(args.resource):
            print(f"{args.resource} is not a valid resource name")
            return 2
        if (prefer or args.resource) and not pool_spec(args.cls):
            print(f"{args.cls} has no pool; --prefer and --resource apply to pool classes")
            return 2
        queued = any(q["id"] == args.id for q in state["queue"][args.cls])
        holder = f"{args.name} {args.what or args.commands}" if args.what or not queued else None
        code, text = queue_entry(state, roster, args.cls, args.id, args.coordinator, holder, args.minutes,
                                 args.gib, args.cpus, args.commands, args.worktree, by=args.name,
                                 prefer=prefer, resource=args.resource)
        if code == 0:
            save(state, machine)
        print(text)
        why = code == 0 and undersized(args.cls, project_key(args.worktree)[0], args.gib, machine["sizeMargin"])
        if why:
            print(f"warning: {why}")
        return code
    finally:
        unlock()


def recycle_granted(cls, lease_id, requeue):
    """Recycle the resource that granted lease lease_id holds, without the lock. Returns (outcome, line):
    recycled or none keep the grant and mark the lease, so a rerun of await-grant does not recycle again;
    destroyed: the reset failed, so the lease is dropped with a release line, the resource destroyed and,
    when requeue, the entry queued again at the front for another resource; unreachable: the same, except
    that the resource is kept and marked failed (out of rotation, files untouched), so no member gets a
    resource that was not reset; gone: the lease no longer holds the resource."""
    held = next((h for h in load()[cls] if h["id"] == lease_id), None)
    if held is None or not held.get("resource"):
        return "gone", f"{lease_id} holds no resource"
    name, coord = held["resource"], held["coordinator"]
    tail = f"for={lease_id} coordinator={coord}"
    outcome, detail = recycle_run(cls, name, held.get("resourceInfo"), lease_id, held.get("worktree"))
    lock()
    try:
        state, machine = load(), load_machine()
        held = next((h for h in state[cls] if h["id"] == lease_id and h.get("resource") == name), None)
        if held is None:
            return "gone", f"{lease_id} no longer holds {name}"
        if outcome in ("recycled", "none"):
            held["recycled"] = True
            if outcome == "recycled":  # facts the recycle found (an ssh alias, uptime) go on the RESOURCE line
                held["resourceInfo"] = {**(held.get("resourceInfo") or {}),
                                        **{k: v for k, v in detail.items() if k != "failed"}}
            save(state, machine)
            return outcome, recycle_note(cls, name, outcome, detail, tail)
        state[cls] = [h for h in state[cls] if h is not held]
        res = find_resource(state, cls, name)
        token = info = None
        if outcome == "unreachable":
            if res is not None and not res.get("op"):
                mark_failed(res, "unreachable", detail)  # out of rotation, kept: resource mark ... --state free returns it
        elif res is not None and not res.get("op"):
            token, info = begin_op(res, "delete", "deleting", lease_id), res.get("info")
        if requeue:
            granted, expires = (dt.datetime.fromisoformat(held[k]) for k in ("grantedAt", "expiresAt"))
            queue_entry(state, load_roster(), cls, lease_id, coord, held["holder"],
                        max(1, round((expires - granted).total_seconds() / 60)),
                        commands=held.get("commands"), worktree=held.get("worktree"), front=True,
                        prefer=held.get("prefer"))  # not wantResource: that resource is gone
        save(state, machine)
        log(f"release {cls} {lease_id} ran 0 min result=fail drained=0 coordinator={coord} "
            f"note={json.dumps(f'recycle of {name} {outcome} at grant: {detail}')}")
    finally:
        unlock()
    if outcome == "unreachable":
        log(f"resource recycle-unreachable {cls} {name} marked failed error={json.dumps(detail)} {tail}")
        say("pool", f"RECYCLE-UNREACHABLE {cls} {name} for {lease_id}: {detail}; not granted, marked failed and kept "
                    f"(check ssh from the server, then resource mark {cls} --name {name} --state free)", coord)
        return "unreachable", f"could not reach {name} to reset it ({detail}); marked failed and kept"
    if token is None:
        log(f"resource destroy-skipped {cls} {name} reason={json.dumps(detail)} {tail} (busy or gone)")
        return "destroyed", f"recycle of {name} failed ({detail}); it is busy or gone, so it was not deleted"
    return "destroyed", destroy_recycled(cls, name, token, info, detail, lease_id, coord)


def await_grant(args):
    """Poll without the lock. The coordinator may queue the ID for the member, so the
    ID gets --appear-timeout to show up before it is judged. Prints HELD <reason> when
    the coordinator holds or reviews the entry, then one final line: GRANTED, DENIED,
    LEFT-QUEUE, TIMEOUT or NEVER-QUEUED <reason>; only GRANTED (exit 0) means granted, and no
    other final line contains the word GRANTED, so a text match cannot read a refusal as a grant. A pool class with a
    recycle command resets the granted resource first (recycle_granted)."""
    start = time.time()
    seen, held, assigning, destroyed = False, None, None, 0
    while True:
        state = load()
        held_lease = next((h for h in state[args.cls] if h["id"] == args.id), None)
        if held_lease and held_lease.get("resource") and not held_lease.get("recycled") \
                and (pool_spec(args.cls) or {}).get("recycle"):
            print(f"RECYCLING {args.cls} {args.id}: {held_lease['resource']}; keep waiting", flush=True)
            outcome, line = recycle_granted(args.cls, args.id, requeue=destroyed + 1 < MAX_RECYCLE_DESTROYS)
            if outcome == "gone":
                seen = True
                continue
            if outcome in ("destroyed", "unreachable"):
                destroyed += 1
                print(f"RECYCLE-{'FAILED' if outcome == 'destroyed' else 'UNREACHABLE'} {args.cls} {args.id}: {line}", flush=True)
                if not any(q["id"] == args.id for q in load()["queue"][args.cls]):
                    print(f"LEFT-QUEUE {args.cls} {args.id}: {destroyed} resource(s) failed their reset; do not run; ask your coordinator")
                    return 3
                print(f"REQUEUED {args.cls} {args.id}: at the front of the queue for another resource; keep waiting", flush=True)
                seen = True
                continue
            print(f"{'RECYCLED' if outcome == 'recycled' else 'NOT-RECYCLED'} {args.cls} {args.id}: {line}", flush=True)  # none: no command
            held_lease = next((h for h in load()[args.cls] if h["id"] == args.id), None)
        if held_lease:
            print(f"GRANTED {args.cls} {args.id}")
            if held_lease.get("resource"):
                print(f"RESOURCE {held_lease['resource']} {json.dumps(held_lease.get('resourceInfo') or {})}")
            return 0
        entry = next((q for q in state["queue"][args.cls] if q["id"] == args.id), None)
        waited = time.time() - start
        denied = (state.get("denied") or {}).get(args.id)
        if entry is None and denied:
            print(f"DENIED {args.cls} {args.id}: {denied['reason']} (by {denied['by']})")
            return 4
        if entry is not None:
            seen = True
            status = (entry.get("reason") or "wait for your coordinator") if entry.get("hold") or entry.get("review") else None
            if status != held:
                held = status
                if held:
                    print(f"HELD {args.cls} {args.id}: {held}", flush=True)
            if entry.get("assigning") != assigning:
                assigning = entry.get("assigning")
                if assigning:
                    print(f"ASSIGNING {args.cls} {args.id}: {assigning}; keep waiting", flush=True)
        elif seen:
            print(f"LEFT-QUEUE {args.cls} {args.id}: left the queue with no lease; do not run; ask your coordinator")
            return 3
        elif waited >= args.appear_timeout:
            print(f"NEVER-QUEUED {args.cls} {args.id}: not queued within {args.appear_timeout:g} s; do not run; check the id with your coordinator")
            return 6
        if waited >= args.timeout_min * 60:
            ready = [q["id"] for q in state["queue"][args.cls] if not q.get("hold")]
            where = (f"position {ready.index(args.id) + 1}" if args.id in ready else "on hold") + "; still queued" \
                if entry else "not queued yet"
            print(f"TIMEOUT {args.cls} {args.id}: after {args.timeout_min:g} min; {where}; do not run; run await-grant again")
            return 5
        nap(args.interval)


def extend(args):
    """Ask for more time on the member's own granted lease. Extension is the coordinator's
    decision (coordinator.py extend), so this only checks the request and logs it."""
    roster, state = load_roster(), load()
    if not any(m["name"] == args.name for m in roster["members"].get(args.coordinator, [])):
        print(f"{args.name} is not a member of {args.coordinator}; send JOIN first")
        return 3
    held = next((h for h in state[args.cls] if h["id"] == args.id), None)
    if held is None:
        print(f"{args.cls} not held by {args.id}; request a new lease")
        return 3
    # A transferred member keeps its old ID prefix, so match the name part and the holder's coordinator.
    if f"-q-{args.name}-" not in args.id or held["coordinator"] != args.coordinator:
        print(f"{args.id} is not yours; extend only a lease granted to you")
        return 3
    why = extension_refusal(held, args.cls, args.minutes)
    if why:
        print(why)
        return 2
    log(f"extend-request {args.cls} {args.id} {args.minutes} min by={args.name} coordinator={args.coordinator} reason={json.dumps(args.reason)}")
    say(args.name, f"EXTEND {args.cls} {args.id} {args.minutes} min: coordinator.py extend {args.cls} --id {args.id} "
        f"--minutes {args.minutes} when the queue allows, else ask the member to release. Reason: {args.reason}", args.coordinator)
    print(f"asked {args.coordinator} to extend {args.cls} {args.id} to {args.minutes} min from now; it still expires at "
          f"{held['expiresAt'][11:16]}Z until {args.coordinator} extends it")
    return 0


def read_peak(path):
    """A measure-peak figure, or None when the file is missing or unreadable."""
    try:
        return float(open(path).read().strip())
    except (OSError, ValueError):
        return None


def release(args):
    """Release the caller's own lease: record its run minutes and measured peak, then
    check what the run left in its worktree (after the lock: the check scans every
    process) and write one event line with the result and the drain count. That line is
    the shared record of the release; other coordinators read it, no one sends a receipt."""
    lock()
    try:
        state, machine = load(), load_machine()
        holders = state[args.cls]
        if not any(h["id"] == args.id for h in holders):
            print(f"{args.cls} not held by {args.id}: {json.dumps(holders)}")
            return 3
        peak, cores = args.peak_gib, args.peak_cpus
        files = [os.path.join(PEAKS, f"{args.id}.{ext}") for ext in ("gib", "cpus")]
        if peak is None:
            peak = read_peak(files[0])
        if cores is None:
            cores = read_peak(files[1])
        held = next(h for h in holders if h["id"] == args.id)
        key = held["project"]
        ran = round((now() - dt.datetime.fromisoformat(held["grantedAt"])).total_seconds() / 60, 1)
        if key:
            proj = load_project(key, held.get("worktree"))
            c = proj["classes"][args.cls]
            for field, value in (("samples", peak), ("cpuSamples", cores)):
                if value:
                    c[field].append(round(value, 1))
                    del c[field][:-SAMPLES_KEPT]
            c["runMinutes"].append(ran)
            del c["runMinutes"][:-MINUTES_KEPT]
            save_project(proj)
        for path in files:
            if os.path.exists(path):
                os.remove(path)
        state[args.cls] = [h for h in holders if h["id"] != args.id]
        res = find_resource(state, args.cls, held.get("resource")) if held.get("resource") else None
        token = info = check = None
        spec = pool_spec(args.cls) or {}
        usable = res is not None and res["state"] == "free" and not res.get("op")
        retired = usable and bool(args.retire_vm)
        if retired:  # never granted again; the server's pool upkeep deletes it, and the next grant gets another
            mark_failed(res, "retire", args.retire_vm)
        elif usable and spec.get("recycle"):  # the recycle checks free disk too
            token, info = begin_op(res, "recycle", "recycling", args.id), res.get("info")  # no grant takes it mid-reset
        elif usable and spec.get("health"):  # a VM left under the floors is retired now, not at the next grant
            check, info = begin_op(res, "health", "checking", args.id), res.get("info")
        elif res and res["state"] == "free":
            set_state(res, "free")  # stamps the idle clock; the server's pool upkeep stops it later, if the class asks
        save(state, machine)
    finally:
        unlock()
    try:
        since = dt.datetime.fromisoformat(held["grantedAt"]) if held.get("grantedAt") else None
        left = drain(held["worktree"], args.port or [], args.process or [], since, args.ignore_pid or []) \
            if held.get("worktree") else []
        for line in left:
            print(f"  {line}")
        peaks = [f"{round(v, 1)} {unit}" for v, unit in ((peak, "GiB"), (cores, "cores")) if v]
        log(f"release {args.cls} {args.id} ran {ran} min" + (f" peak {' '.join(peaks)}" if peaks else "")
            + f" result={args.result} drained={len(left)} coordinator={held['coordinator']}"
            + (f" note={json.dumps(args.note)}" if args.note else ""))
        print(f"released {args.cls} {args.id} ({args.result}); {'drained' if not left else 'not drained'}: {len(left)} left in {held.get('worktree')}")
        if retired:
            print(f"{held['resource']} is retired ({args.retire_vm}): marked failed, never granted again, and deleted by the pool upkeep")
        if token:
            print(f"recycling {held['resource']}; this can take a few minutes", flush=True)
        if check:
            print(f"checking the health of {held['resource']}", flush=True)
    finally:
        # A print raises ClientGone when the client has gone; the claimed resource still gets its recycle or check.
        outcome = token and recycle_released(args.cls, held["resource"], token, info, args.id, held["coordinator"], held.get("worktree"))
        outcome = outcome or (check and health_released(args.cls, held["resource"], check, info, args.id,
                                                         held["coordinator"], held.get("worktree")))
    if outcome:
        print(outcome)
    return 0


# ---------------------------------------------------------------- scouts

SEV_RANK = {s: i for i, s in enumerate(SCOUT_SEVERITIES)}  # P0 first


def scout_cmd(args):
    """A scout's own watch state file (references/scouts.md): tick, alert, resolve, paused, show.
    Only the scout itself writes it; the coordinator heartbeat and the dashboard read it."""
    roster = load_roster()
    m = next((x for x in roster["members"].get(args.coordinator, []) if x["name"] == args.name), None)
    if m is None or m.get("role") != "scout":
        print(f"{args.name} is not a scout of {args.coordinator}; send SCOUT JOIN first")
        return 3
    st = scout_state(args.name)
    if args.scmd == "show":
        print(json.dumps(st, indent=1))
        return 0
    t = now().isoformat()
    st.setdefault("openAlerts", [])
    st["tickMin"] = m.get("tickMin", 15)
    out = ""
    if args.scmd == "tick":
        st["lastTick"] = t
        if args.summary:
            st["summary"] = {"at": t, "text": args.summary}
        out = f"tick {t[:19]}Z; {len(st['openAlerts'])} open"
    elif args.scmd == "alert":
        old = next((a for a in st["openAlerts"] if a["fingerprint"] == args.fingerprint), None)
        if old is None:
            st["openAlerts"].append({"fingerprint": args.fingerprint, "severity": args.severity, "kind": args.kind,
                                     "text": args.text, "firstSeen": t, "lastSeen": t})
            out = "NEW: send it"
        else:
            worse = SEV_RANK[args.severity] < SEV_RANK[old["severity"]]
            out = f"ESCALATED {old['severity']} to {args.severity}: send it" if worse else "SEEN: do not send it again"
            old.update({"lastSeen": t, "text": args.text, "kind": args.kind,
                        "severity": args.severity if worse else old["severity"]})
        st["lastTick"] = t
    elif args.scmd == "resolve":
        left = [a for a in st["openAlerts"] if a["fingerprint"] != args.fingerprint]
        out = ("RESOLVED: send UPDATE recovered" if len(left) < len(st["openAlerts"])
               else f"{args.fingerprint} is not open")
        st["openAlerts"] = left
        st["lastTick"] = t
    elif args.scmd == "paused":
        if args.clear:
            st.pop("pausedSince", None)
            out = "not paused"
        else:
            st.setdefault("pausedSince", t)
            out = f"paused since {st['pausedSince'][:19]}Z"
    write_json(scout_path(args.name), st)
    print(out)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="puppet.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    add_read_commands(sub)
    rq = sub.add_parser("request")
    rq.add_argument("cls", metavar="CLASS")
    rq.add_argument("--coordinator", required=True)
    rq.add_argument("--name", required=True, help="your member name")
    rq.add_argument("--id", help="<coordinator>-q-<name>-<n>; default: the next free n, printed as ID <id>. "
                    "Pass the same id again to change a queued request")
    rq.add_argument("--minutes", type=int, required=True, help="your estimate")
    rq.add_argument("--commands", required=True, help="the exact commands the lease would cover")
    rq.add_argument("--worktree", required=True, help="sets the project whose class peak applies")
    rq.add_argument("--gib", type=float, help="expected peak GiB; omit to let your coordinator charge its own figure")
    rq.add_argument("--cpus", type=float, help="expected peak cores; omit to let your coordinator charge its own figure")
    rq.add_argument("--prefer", action="append", metavar="KEY=VALUE",
                    help="pool class: take a resource whose info matches first (for example slotType=native); the create command gets MOP_PREFER_<KEY>")
    rq.add_argument("--resource", help="pool class: exactly this resource; exit 3 at acquire if it is held, busy or failed; never another one, never a new one")
    rq.add_argument("--what", help="short label for the dashboard; default: the commands")
    ag = sub.add_parser("await-grant")
    ag.add_argument("cls", metavar="CLASS", nargs="?", help="default: the class that queues or holds --id")
    ag.add_argument("--id", required=True)
    ag.add_argument("--timeout-min", type=float, default=30)
    ag.add_argument("--appear-timeout", type=float, default=600, help="seconds the ID may take to be queued")
    ag.add_argument("--interval", type=float, default=10)
    x = sub.add_parser("extend")
    x.add_argument("cls", metavar="CLASS", nargs="?", help="default: the class that queues or holds --id")
    x.add_argument("--coordinator", required=True)
    x.add_argument("--name", required=True, help="your member name")
    x.add_argument("--id", required=True)
    x.add_argument("--minutes", type=int, required=True, help="ask for the lease to expire this many minutes from now")
    x.add_argument("--reason", required=True, help="one short line: what is still running")
    r = sub.add_parser("release")
    r.add_argument("cls", metavar="CLASS", nargs="?", help="default: the class that queues or holds --id")
    r.add_argument("--id", required=True)
    r.add_argument("--retire-vm", metavar="REASON", help="pool class: the resource is dirty or unusable; never grant it "
                   "again, and the pool deletes it. A plain --result fail keeps it when its health check passes")
    r.add_argument("--peak-gib", type=float, help="measured peak; default: peaks/<id>.gib from measure-peak")
    r.add_argument("--peak-cpus", type=float, help="measured peak cores; default: peaks/<id>.cpus from measure-peak")
    r.add_argument("--result", required=True, choices=("pass", "fail", "partial"), help="the outcome of the granted commands")
    r.add_argument("--note", help="one short line, for example 'pushed #123' or the first failure")
    r.add_argument("--port", type=int, action="append", help="also check for listeners on this port (E2E)")
    r.add_argument("--process", action="append", help="also count processes matching this pattern (pgrep -f)")
    r.add_argument("--ignore-pid", type=int, action="append", help="a process in the worktree that the run did not start "
                   "(for example your own wait loop); name the reason in --note")
    sc = sub.add_parser("scout", help="a scout's own watch state (references/scouts.md); never put a secret in --text or --summary")
    scs = sc.add_subparsers(dest="scmd", required=True)
    for name, what in (("tick", "record a check; QUIET ticks go here only"), ("alert", "open or refresh an alert; prints whether to send it"),
                       ("resolve", "close an alert; prints whether to send UPDATE"), ("paused", "a send returned Paused"),
                       ("show", "print the state file")):
        x = scs.add_parser(name, help=what)
        x.add_argument("--coordinator", required=True)
        x.add_argument("--name", required=True, help="your scout name")
        if name == "tick":
            x.add_argument("--summary", help="the daily SUMMARY, kept in the file instead of a message")
        if name in ("alert", "resolve"):
            x.add_argument("--fingerprint", required=True, help="monitor or issue id plus the cause")
        if name == "alert":
            x.add_argument("--severity", required=True, choices=SCOUT_SEVERITIES)
            x.add_argument("--kind", choices=("alert", "gap"), default="alert", help="gap: your own read failed")
            x.add_argument("--text", required=True, help="one line; the location of a secret, never its value")
        if name == "paused":
            x.add_argument("--clear", action="store_true", help="sends work again")
    args = p.parse_args(argv)
    if args.cmd == "scout":
        return scout_cmd(args)
    if args.cmd in ("await-grant", "extend", "release") and not args.cls:
        args.cls = class_of(args.id)
        if not args.cls:
            p.error(f"{args.id} is not queued or held in any class; give CLASS")
    name = getattr(args, "cls", None)
    if name and name not in registry():
        p.error(f"unknown lease class {name}; known: {', '.join(class_names())}")
    if args.cmd in ("roster", "whoami"):
        version_warning()
    if args.cmd in READS:
        return read_cmd(args)
    if args.cmd == "request":
        return request(args)
    if args.cmd == "await-grant":
        return await_grant(args)
    if args.cmd == "extend":
        return extend(args)
    return release(args)


if __name__ == "__main__":
    sys.exit(forward("puppet", sys.argv[1:]))
