#!/usr/bin/env python3
"""Repair a DeepSeek Harness session log so the app can open it again.

Why this exists
---------------
A session log (`session.v4.jsonl.zstd`) is an append-only event stream that the
loader validates strictly:

* the **first zstd frame must contain exactly the header line** (and nothing else),
* event `seq` numbers must be contiguous from 0,
* `sourceEventSeqs` may only reference *earlier, unique* seqs,
* replacement events (`surfaceOp` as an object) must reference the node they
  shadow,
* the `turn/start -> step/start -> ... -> step/end -> turn/end` state machine
  must stay balanced.

Any external edit (trimming history, renumbering, moving events) can break one of
those invariants, and the app then **hides the session or refuses to open it**
without saying which invariant failed.

What this tool does
-------------------
`--mode reframe`  (safe, non-destructive to content)
    Re-splits the log into the two-frame layout the loader expects.

`--mode normalize`  (rewrites numbers; keeps every event it can)
    Renumbers events contiguously from 0 and drops references that no longer
    make sense (`sourceEventSeqs`), turning replacement events into plain
    appends so their stale surface references stop failing validation.

`--mode repair`  (most aggressive)
    normalize + drops events that fail basic envelope checks + re-frames.

Every mode writes `*.bak-<timestamp>` next to the original and never touches a
log while the app is running. Stop the app first.

Usage
-----
    python3 session_repair.py --dir ~/.dsh/sessions --mode normalize
    python3 session_repair.py --file ~/.dsh/sessions/<ws>/<sid>/session.v4.jsonl.zstd --mode repair
    python3 session_repair.py --dir ~/.dsh/sessions --mode reframe --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

NEWLINE = b'\n'


def decompress(path: str) -> bytes:
    return subprocess.run(['zstdcat', path], capture_output=True, check=True).stdout


def write_two_frames(raw: bytes, path: str) -> None:
    """Write raw as: frame 1 = header line only, frame 2 = everything else."""
    index = raw.find(NEWLINE)
    if index < 0:
        raise ValueError('log has no header line')
    head = tempfile.NamedTemporaryFile(delete=False)
    head.write(raw[: index + 1])
    head.close()
    tail = tempfile.NamedTemporaryFile(delete=False)
    tail.write(raw[index + 1 :])
    tail.close()
    out = path + '.new'
    with open(out, 'wb') as handle:
        subprocess.run(['zstd', '-q', '-19', '-c', head.name], stdout=handle, check=True)
        if raw[index + 1 :]:
            subprocess.run(['zstd', '-q', '-19', '-c', tail.name], stdout=handle, check=True)
    os.replace(out, path)
    os.unlink(head.name)
    os.unlink(tail.name)


def parse_events(raw: bytes) -> tuple[dict, list[dict], int]:
    header: dict | None = None
    events: list[dict] = []
    dropped = 0
    for line in raw.decode('utf-8', 'replace').split('\n'):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            dropped += 1
            continue
        if header is None:
            header = value
        else:
            events.append(value)
    if header is None:
        raise ValueError('empty log')
    return header, events, dropped


def serialize(header: dict, events: list[dict]) -> bytes:
    body = '\n'.join(json.dumps(event, ensure_ascii=False) for event in [header, *events])
    return (body + '\n').encode('utf-8')


def normalize(events: list[dict]) -> list[dict]:
    """Contiguous seqs + drop references that cannot be satisfied any more."""
    kept: list[dict] = []
    for index, event in enumerate(events):
        event['seq'] = index
        refs = event.get('sourceEventSeqs')
        if isinstance(refs, list):
            flat: list[int] = []
            ok = True
            for item in refs:
                if isinstance(item, list) and len(item) == 2:
                    flat.extend(range(item[0], item[1] + 1))
                elif isinstance(item, int):
                    flat.append(item)
                else:
                    ok = False
                    break
            if not ok or any(ref >= index or ref < 0 for ref in flat):
                event.pop('sourceEventSeqs', None)
        if isinstance(event.get('surfaceOp'), dict):
            # A replacement whose shadowed node may be gone is safer as an append.
            event['surfaceOp'] = 'append'
            event.pop('sourceEventSeqs', None)
        kept.append(event)
    return kept


def repair_one(path: str, mode: str, dry_run: bool) -> str:
    raw = decompress(path)
    header, events, dropped = parse_events(raw)
    if mode == 'reframe':
        if not dry_run:
            shutil.copy2(path, f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
            write_two_frames(raw if raw.endswith(NEWLINE) else raw + NEWLINE, path)
        return f'{os.path.basename(os.path.dirname(path))[:40]} reframed'
    events = normalize(events)
    body = serialize(header, events)
    if not dry_run:
        shutil.copy2(path, f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
        write_two_frames(body, path)
    return f'{os.path.basename(os.path.dirname(path))[:40]} {mode} events={len(events)} dropped={dropped}'


def iter_logs(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name == 'session.v4.jsonl.zstd':
                yield os.path.join(dirpath, name)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--dir', help='recursively repair every session log under this directory')
    target.add_argument('--file', help='repair a single session.v4.jsonl.zstd')
    parser.add_argument('--mode', choices=['reframe', 'normalize', 'repair'], default='normalize')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)

    paths = list(iter_logs(args.dir)) if args.dir else [args.file]
    if not paths:
        print('no session logs found', file=sys.stderr)
        return 1
    failures = 0
    for path in paths:
        try:
            print(repair_one(path, args.mode, args.dry_run))
        except Exception as error:  # noqa: BLE001 - report and continue
            failures += 1
            print(f'FAILED {path}: {error}', file=sys.stderr)
    print(f'processed {len(paths)} log(s), {failures} failure(s)')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
