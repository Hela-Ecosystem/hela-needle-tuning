#!/usr/bin/env python3
"""Write data/seed/contrast_siblings.jsonl: templated rows aimed at the confusions the first
per-profile model made (see issue #8): look-alike file tools, local vs remote shell tools,
memory search vs git analysis, bare city names vs IANA zones, convert_time direction, and
paths that end a sentence or have no extension.

Deterministic (fixed seed) so the file can be regenerated. Every row is forced to the train split;
the frozen eval is hand written and never touched.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "seed" / "contrast_siblings.jsonl"
R = random.Random(20261127)
rows: list[dict] = []


# The eval must stay unseen: skip any row whose task text, or whose tool plus arguments, an eval row has.
sys.path.insert(0, str(OUT.parent.parent.parent / "src"))
from hela_needle.splits import split_of  # noqa: E402


def _eval_rows() -> list[dict]:
    """Every seed line that lands in the eval split, whichever file it is in (hand written or hash split)."""
    out = []
    for f in sorted(OUT.parent.glob("*.jsonl")):
        if f == OUT:
            continue
        for l in f.read_text(encoding="utf8").splitlines():
            if not l.strip() or l.lstrip().startswith("#"):
                continue
            item = json.loads(l)
            if (item.get("split") or split_of(item["task"], bool(item.get("regression")))) == "eval":
                out.append(item)
    return out


_EVAL = _eval_rows()
EVAL_TASKS = {e["task"].strip().lower() for e in _EVAL}
EVAL_CALLS = {(e.get("tool"), json.dumps(e.get("arguments"), sort_keys=True)) for e in _EVAL if e.get("arguments") is not None}
SKIPPED = 0


def add(task: str, tool: str, args: dict | None, note: str) -> None:
    global SKIPPED
    if task.strip().lower() in EVAL_TASKS or (args is not None and (tool, json.dumps(args, sort_keys=True)) in EVAL_CALLS):
        SKIPPED += 1
        return
    row = {"task": task, "tool": tool, "split": "train", "note": note}
    if args is not None:
        row["arguments"] = args
    rows.append(row)


M, N, G, T = "hela_membrane_", "hela_nucleus_", "hela_genome_", "hela_mitosis_"

# --- time zones: spoken city -> IANA name; convert_time keeps source and target apart ---
ZONES = {
    "Tokyo": "Asia/Tokyo", "London": "Europe/London", "Auckland": "Pacific/Auckland", "Jakarta": "Asia/Jakarta",
    "Berlin": "Europe/Berlin", "New York": "America/New_York", "Sydney": "Australia/Sydney", "Paris": "Europe/Paris",
    "Singapore": "Asia/Singapore", "Dubai": "Asia/Dubai", "Mumbai": "Asia/Kolkata", "Los Angeles": "America/Los_Angeles",
    "Sao Paulo": "America/Sao_Paulo", "Cairo": "Africa/Cairo", "Amsterdam": "Europe/Amsterdam", "Seoul": "Asia/Seoul",
    "Chicago": "America/Chicago", "Toronto": "America/Toronto", "Madrid": "Europe/Madrid", "Bangkok": "Asia/Bangkok",
}
for city, tz in ZONES.items():
    for tpl in ("What time is it in {c} right now?", "Current time in {c}, please.", "what's the local time in {c}", "Tell me the time in {c}. Do not modify any files."):
        if R.random() < 0.6:
            add(tpl.format(c=city), T + "get_current_time", {"timezone": tz}, "iana: city -> full zone")
    add(f"What time is it in {tz}?", T + "get_current_time", {"timezone": tz}, "iana: zone given")

cities = list(ZONES)
for _ in range(70):
    a, b = R.sample(cities, 2)
    hh, mm = R.choice([9, 10, 12, 14, 15, 17, 18, 20, 22]), R.choice([0, 0, 30, 15, 45])
    t24 = f"{hh:02d}:{mm:02d}"
    spoken = (f"{hh % 12 or 12}{'' if mm == 0 else f':{mm:02d}'}{'am' if hh < 12 else 'pm'}")
    tpl = R.choice([
        ("Convert {t} {a} time to {b}", False), ("What is {t} in {a} in {b} time?", False),
        ("When it is {t} in {a}, what time is it in {b}?", False), ("Convert {s} {a} time to {b} time", True),
        ("I have a call at {s} {a} time. What time is that in {b}?", True),
    ])
    add(tpl[0].format(t=t24, s=spoken, a=a, b=b), T + "convert_time", {"source_timezone": ZONES[a], "time": t24, "target_timezone": ZONES[b]}, "convert_time: source is the first city, target the second")

# --- file tools that look alike ---
DIRS = ["/workspace", "/workspace/src", "/workspace/docs", "/workspace/tests", "/home/dev/project", "/srv/app", "/var/www/site"]
FILES = ["README.md", "notes.txt", "config.json", "main.py", "package.json", "NOTICE", "LICENSE", "Makefile", "Dockerfile", "CHANGELOG.md", "app.log", "schema.sql", "index.html", "settings.yaml"]


def path() -> str:
    return f"{R.choice(DIRS)}/{R.choice(FILES)}"


for _ in range(60):
    p = path()
    add(R.choice(["Show me the contents of {p}.", "Show me the contents of {p}. Do not modify any files.", "What does {p} say?", "Read {p} and tell me what is in it.", "Print the text of {p}", "Open {p} and show it to me."]).format(p=p), M + "read_file", {"path": p}, "contrast: read_file (content), path copied without trailing period")
for _ in range(45):
    p = path()
    add(R.choice(["How big is {p}?", "When was {p} last modified?", "What are the permissions on {p}?", "Get the file size and modification date of {p}.", "Is {p} a symlink, and how large is it?"]).format(p=p), M + "get_file_info", {"path": p}, "contrast: get_file_info (metadata, not content)")
for _ in range(40):
    d = R.choice(DIRS)
    add(R.choice(["List the files in {d}.", "What is inside the folder {d}?", "Show me everything in {d}", "ls {d} for me, please."]).format(d=d), M + "list_directory", {"path": d}, "contrast: list_directory")
for _ in range(30):
    d, ext = R.choice(DIRS), R.choice(["py", "md", "json", "log", "ts"])
    add(R.choice(["Find every .{e} file under {d}.", "Locate all *.{e} files in {d}", "Which .{e} files exist in {d}, searching subfolders?"]).format(e=ext, d=d), M + "find_files", {"pattern": f"*.{ext}", "directory": d}, "contrast: find_files (by name pattern)")
for _ in range(30):
    d, word = R.choice(DIRS), R.choice(["TODO", "FIXME", "deprecated", "localhost", "password_hash", "retry_count"])
    add(R.choice(["Search {d} for the text {w}.", "Which files in {d} contain {w}?", "grep for {w} in {d}"]).format(d=d, w=word), M + "search_in_files", {"pattern": word, "directory": d}, "contrast: search_in_files (by content)")
for _ in range(40):
    p, text = path(), R.choice(["call back at noon", "draft v2", "release candidate", "TODO: review", "hello world", "version=2"])
    add(R.choice(["Write '{t}' into {p}", "Save the text '{t}' to {p}", "Replace the content of {p} with '{t}'"]).format(t=text, p=p), M + "write_file", {"path": p, "content": text}, "contrast: write_file (one file's content), not archive")
for _ in range(30):
    d = R.choice(DIRS)
    names = R.sample(FILES, 2)
    files = [f"{d}/{n}" for n in names]
    out = f"{d}/backup-{R.randint(1, 30)}.zip"
    add(R.choice(["Zip {a} and {b} into {o}.", "Archive {a} and {b} as {o}", "Compress {a} and {b} into the archive {o}"]).format(a=files[0], b=files[1], o=out), M + "archive_files", {"files": files, "archivePath": out, "format": "zip"}, "contrast: archive_files (bundle several files), not write")

# --- local shell vs remote terminal tools ---
for cmd, say in [("pytest -q", "Run the tests with pytest -q"), ("df -h", "Check disk usage with df -h"), ("git status", "Run git status in the project"), ("npm run build", "Run npm run build"), ("uname -a", "Show the kernel version with uname -a"), ("docker ps", "List the running containers with docker ps")]:
    add(say, N + "execute_command", {"command": cmd}, "contrast: execute_command (local, no host)")
for host, user in [("web-1", "deploy"), ("db-2", "admin"), ("build-3", "ci")]:
    d = R.choice(["/var/log", "/etc/nginx", "/opt/app"])
    add(f"List {d} on host {host} as user {user}.", N + "terminal_ls", {"path": d, "host": host, "username": user}, "contrast: terminal_ls (remote host named)")
    add(f"Read {d}/app.log on {host} as {user}.", N + "terminal_cat", {"path": f"{d}/app.log", "host": host, "username": user}, "contrast: terminal_cat (remote host named)")

# --- memory graph vs git analysis ---
for q in ["deployment decisions", "the auth refactor", "database migration plan", "release checklist", "why we chose SQLite"]:
    add(R.choice(["Search the memory graph for {q}.", "Find what we stored about {q}.", "Look up {q} in project memory."]).format(q=q), G + "search_nodes", {"query": q}, "contrast: search_nodes (memory), not git")
for task, a in [("What changed in my uncommitted work?", {}), ("Analyse the changes from the last 3 commits.", {"since": "3"}), ("Summarise the uncommitted diff.", {}), ("What did the last commit change?", {"since": "1"})]:
    add(task, G + "analyze_git_changes", a, "contrast: analyze_git_changes (git diff), not memory")

OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
print(f"wrote {len(rows)} rows -> {OUT} (left out {SKIPPED} that the eval already covers)", file=sys.stderr)
