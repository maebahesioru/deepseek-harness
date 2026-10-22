# session-repair

Offline repair for DeepSeek Harness session logs (`session.v4.jsonl.zstd`), plus
the `DSH_SESSION_SALVAGE` load mode that keeps a damaged session usable.

## The problem

A session log is an append-only event stream validated on every load:

| Invariant | Error you see |
|---|---|
| first zstd frame holds **only** the header line | `corrupt Zstandard session log: first frame is not exactly one header line` |
| `seq` contiguous from 0 | `released v2 row 6 has seq gap (expected 6, got 0)` |
| `sourceEventSeqs` only reference earlier, unique seqs | `sourceEventSeqs ranges must contain unique earlier seqs` |
| replacement events reference the node they shadow | `replacement sourceEventSeqs omit a shadowed surface node` |
| balanced `turn/start` → `step/start` → … → `step/end` → `turn/end` | `assistant/message does not match an open turn and step` |

Any tool that edits history outside the app (trimming long transcripts,
renumbering, moving events between files) can break one of these. The app then
**hides the session from the sidebar or refuses to open it**, and the error names
an internal invariant rather than the edit that broke it.

## Two ways out

### 1. `DSH_SESSION_SALVAGE=1` — keep the readable prefix

When set, seed loading stops at the first structurally invalid event and keeps
everything before it instead of rejecting the whole session:

```bash
DSH_SESSION_SALVAGE=1 deepseek-harness
```

`Session.seedTruncation` reports `{ kept, total }` when a log was truncated this
way, so a UI can show "history partially recovered". The on-disk log is never
modified in this mode.

### 2. `session_repair.py` — fix the log itself

```bash
# stop the app first: the log must not be written while it runs
python3 tools/session-repair/session_repair.py --dir ~/.dsh/sessions --mode reframe --dry-run
python3 tools/session-repair/session_repair.py --dir ~/.dsh/sessions --mode normalize
```

Modes:

* `reframe` — only re-splits the zstd framing (first frame = header line). Use it
  when the content is right but the file was re-compressed as a single frame.
* `normalize` — re-frames **and** renumbers `seq` contiguously, drops references
  that point at events that no longer exist, and turns replacement events into
  plain appends so stale surface references stop failing.
* `repair` — normalize plus dropping lines that are not valid JSON (interrupted
  writes).

Every mode copies the original to `*.bak-<timestamp>` first. Nothing is deleted
from disk unless you remove the backups yourself.

## Notes

* `reframe`/`normalize` are lossless with respect to message content; they only
  change numbers and framing.
* A replacement event downgraded to `append` keeps its payload but loses
  "this supersedes that" semantics — acceptable for reading old history, and it
  is what makes otherwise unreadable sessions loadable again.
* Salvage and repair are escape hatches, not a substitute for fixing whatever
  rewrote the log in the first place.

## Verifying a batch

```bash
for f in $(find ~/.dsh/sessions -name 'session.v4.jsonl.zstd'); do
  zstdcat "$f" | python3 -c '
import json, sys
seqs = [json.loads(line)["seq"] for line in sys.stdin if line.strip() and "seq" in line]
print("ok" if seqs == list(range(len(seqs))) else "seq-gap")
'
done | sort | uniq -c
```
