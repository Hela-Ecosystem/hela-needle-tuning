#!/usr/bin/env python3
"""Expand hand-written phrasings into data/seed/expanded.jsonl.

Deterministic (fixed seed) so the committed output can be regenerated and
diffed. Each entry maps a qualified tool name to phrasing templates and the
argument sets that fill them. ``{k}`` placeholders are filled from the
argument set; ``args`` is what the tool call must contain. The builder
validates every row against the catalog, so a renamed tool or changed schema
fails loudly instead of teaching stale calls.

Usage: python scripts/expand_seeds.py [--per-tool 12] [--out data/seed/expanded.jsonl]
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from pathlib import Path

READ_ONLY_SUFFIX = [" Do not modify any files.", " Don't change anything.", " Read only, please.", " Without changing anything."]

# tool -> (phrasings, [argument sets]); {name} in a phrasing is filled from the set.
SPEC: dict[str, tuple[list[str], list[dict]]] = {
    "hela_mitosis_get_current_time": (
        ["What time is it in {place}?", "Tell me the current time in {place}.", "Give me the date and time in {place}.", "What is the local time in {place} right now?", "Current time for {tz}, please."],
        [{"place": "Jakarta", "tz": "Asia/Jakarta"}, {"place": "Tokyo", "tz": "Asia/Tokyo"}, {"place": "London", "tz": "Europe/London"}, {"place": "New York", "tz": "America/New_York"}, {"place": "Sydney", "tz": "Australia/Sydney"}, {"place": "Berlin", "tz": "Europe/Berlin"}, {"place": "Singapore", "tz": "Asia/Singapore"}, {"place": "Los Angeles", "tz": "America/Los_Angeles"}],
    ),
    "hela_mitosis_convert_time": (
        ["Convert {time} from {src} to {dst}.", "What is {time} {src} in {dst}?", "When it is {time} in {src}, what time is it in {dst}?"],
        [{"time": "14:30", "src": "Asia/Jakarta", "dst": "America/New_York"}, {"time": "09:00", "src": "Europe/London", "dst": "Asia/Tokyo"}, {"time": "22:15", "src": "America/Los_Angeles", "dst": "Europe/Berlin"}, {"time": "07:45", "src": "Asia/Singapore", "dst": "Australia/Sydney"}],
    ),
    "hela_membrane_list_directory": (
        ["List the files in {path}.", "What is in {path}?", "Show the directory listing of {path}.", "Show me what files are inside {path}."],
        [{"path": "/workspace"}, {"path": "/workspace/src"}, {"path": "/workspace/docs"}, {"path": "/workspace/tests"}, {"path": "/workspace/scripts"}, {"path": "/workspace/config"}],
    ),
    "hela_membrane_read_file": (
        ["Read {path}.", "Show me the contents of {path}.", "Open {path} and tell me what it says.", "What is written in {path}?"],
        [{"path": "/workspace/README.md"}, {"path": "/workspace/package.json"}, {"path": "/workspace/src/index.ts"}, {"path": "/workspace/config/settings.yaml"}, {"path": "/workspace/docs/guide.md"}, {"path": "/workspace/CHANGELOG.md"}],
    ),
    "hela_membrane_write_file": (
        ["Create {path} containing '{content}'.", "Write '{content}' to {path}.", "Save the text '{content}' in a new file {path}."],
        [{"path": "/workspace/notes.txt", "content": "meeting at 3pm"}, {"path": "/workspace/todo.md", "content": "- buy milk"}, {"path": "/workspace/out/result.txt", "content": "done"}, {"path": "/workspace/hello.txt", "content": "hello world"}],
    ),
    "hela_membrane_copy_file": (
        ["Copy {source} to {destination}.", "Make a backup of {source} as {destination}.", "Duplicate {source} into {destination}."],
        [{"source": "/workspace/config.json", "destination": "/workspace/config.backup.json"}, {"source": "/workspace/src/app.ts", "destination": "/workspace/src/app.copy.ts"}, {"source": "/workspace/data.csv", "destination": "/workspace/archive/data.csv"}],
    ),
    "hela_membrane_get_file_info": (
        ["How big is {path}?", "When was {path} last modified?", "Give me the size and permissions of {path}."],
        [{"path": "/workspace/data.db"}, {"path": "/workspace/build/app.js"}, {"path": "/workspace/README.md"}],
    ),
    "hela_membrane_find_files": (
        ["Find every {label} file under {directory}.", "Locate all {label} files in {directory}."],
        [{"label": "TypeScript", "pattern": "*.ts", "directory": "/workspace/src"}, {"label": "markdown", "pattern": "*.md", "directory": "/workspace"}, {"label": "JSON", "pattern": "*.json", "directory": "/workspace/config"}, {"label": "test", "pattern": "*.test.*", "directory": "/workspace/tests"}],
    ),
    "hela_membrane_search_in_files": (
        ["Search the code for the text {pattern}.", "Which files mention {pattern}?", "grep for {pattern} in the project."],
        [{"pattern": "TODO"}, {"pattern": "FIXME"}, {"pattern": "deprecated"}, {"pattern": "console.log"}],
    ),
    "hela_membrane_delete_file": (
        ["Delete {path}.", "Remove the file {path}.", "Get rid of {path}."],
        [{"path": "/workspace/tmp/scratch.log"}, {"path": "/workspace/old/notes.bak"}, {"path": "/workspace/build/cache.tmp"}],
    ),
    "hela_nucleus_execute_command": (
        ["{ask}", "{ask} Use the shell."],
        [{"ask": "Check how much disk space is free.", "command": "df -h"}, {"ask": "Run the test suite.", "command": "npm test"}, {"ask": "Show the git status of the repository.", "command": "git status"}, {"ask": "Show the last five commits.", "command": "git log --oneline -5"}, {"ask": "Which version of Node is installed?", "command": "node --version"}, {"ask": "Show memory usage.", "command": "free -m"}],
    ),
    "hela_nucleus_terminal_ls": (
        ["List {path} in the terminal with details.", "Run ls on {path}."],
        [{"path": "/workspace/src"}, {"path": "/workspace"}, {"path": "/workspace/logs"}],
    ),
    "hela_nucleus_terminal_session_list": (
        ["Which terminal sessions are open?", "List my terminal sessions.", "Show the active shell sessions."],
        [{}],
    ),
    "hela_ribosome_session_spawn": (
        ["Start an interactive {command} session I can keep using.", "Open a persistent {command} PTY."],
        [{"command": "bash"}, {"command": "python3"}, {"command": "node"}],
    ),
    "hela_ribosome_session_list": (
        ["Which PTY sessions are currently running?", "List the running PTY sessions.", "Show all managed terminal processes."],
        [{}],
    ),
    "hela_genome_search_nodes": (
        ["Look up what we know about {query} in memory.", "Search the knowledge graph for {query}.", "Do we have any notes on {query}?"],
        [{"query": "deployment pipeline"}, {"query": "auth service"}, {"query": "release process"}, {"query": "database schema"}],
    ),
    "hela_genome_read_graph": (
        ["Show me the whole knowledge graph.", "Dump the memory graph.", "Read the entire knowledge graph."],
        [{}],
    ),
    "hela_genome_query_data": (
        ["Read the first {limit} rows of the {table} table.", "Show {limit} records from {table}."],
        [{"table": "sessions", "limit": 20}, {"table": "missions", "limit": 10}, {"table": "events", "limit": 50}],
    ),
    "hela_cytosol_browser_navigate": (
        ["Open {url} in the browser.", "Go to {url}.", "Navigate the browser to {url}."],
        [{"url": "https://example.com"}, {"url": "https://news.ycombinator.com"}, {"url": "https://docs.python.org/3/"}, {"url": "https://github.com"}],
    ),
    "hela_cytosol_browser_screenshot": (
        ["Take a screenshot of the current page.", "Capture the page as an image.", "Screenshot what the browser is showing."],
        [{}],
    ),
    "hela_cytosol_browser_get_content": (
        ["Get the text content of the page that is open.", "Read the text of the current web page.", "Extract the content of the open page."],
        [{}],
    ),
    "hela_enzyme_wikipedia_search": (
        ["Search Wikipedia for {query}.", "Find the Wikipedia article about {query}.", "Look up {query} on Wikipedia."],
        [{"query": "Krebs cycle"}, {"query": "Alan Turing"}, {"query": "Transformer architecture"}, {"query": "Mount Merapi"}],
    ),
    "hela_enzyme_google_search": (
        ["Search Google for {q}.", "Google {q}.", "Search the web for {q}."],
        [{"q": "latest Node.js LTS version"}, {"q": "best practices for SQLite WAL"}, {"q": "rust vs go for cli tools"}],
    ),
    "hela_enzyme_academic_search": (
        ["Find academic papers about {query}.", "Search arXiv for {query}.", "Look for research on {query}."],
        [{"query": "retrieval augmented generation"}, {"query": "tool calling small language models"}, {"query": "LoRA fine-tuning"}],
    ),
}

# Which argument keys go into the call (the rest only fill the phrasing).
ARG_KEYS = {
    "hela_mitosis_get_current_time": {"timezone": "tz"},
    "hela_mitosis_convert_time": {"source_timezone": "src", "time": "time", "target_timezone": "dst"},
}

READ_TOOLS = {"hela_mitosis_get_current_time", "hela_membrane_list_directory", "hela_membrane_read_file", "hela_membrane_get_file_info", "hela_membrane_find_files", "hela_membrane_search_in_files", "hela_genome_search_nodes", "hela_genome_read_graph"}
NEGATIVES = [
    ("Thanks, that is everything I needed.", "done"), ("That's all, thank you.", "done"), ("Nothing else is needed, we are finished.", "done"),
    ("Everything you were asked has already been completed.", "done"), ("All done here, no further action.", "done"),
    ("Tell me a joke about penguins.", None), ("What is the meaning of life?", None), ("Write me a poem about autumn.", None),
    ("How are you today?", None), ("Who won the world cup in 2010?", None),
]


def call_args(tool: str, values: dict) -> dict:
    mapping = ARG_KEYS.get(tool)
    if mapping:
        return {arg: values[key] for arg, key in mapping.items()}
    return {k: v for k, v in values.items() if k not in ("label", "ask", "place")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tool", type=int, default=12)
    ap.add_argument("--out", default="data/seed/expanded.jsonl")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    seen: set[str] = set()
    lines: list[dict] = []
    for tool, (phrasings, sets) in SPEC.items():
        combos = list(itertools.product(phrasings, sets))
        rng.shuffle(combos)
        taken = 0
        for phrase, values in combos:
            if taken >= a.per_tool:
                break
            task = phrase.format(**values) if values else phrase
            if tool in READ_TOOLS and rng.random() < 0.3:
                task += rng.choice(READ_ONLY_SUFFIX)
            key = task.lower()
            if key in seen:
                continue
            seen.add(key)
            args = call_args(tool, values)
            lines.append({"task": task, "tool": tool, **({"arguments": args} if args else {})})
            taken += 1
    for task, tool in NEGATIVES:
        if task.lower() not in seen:
            lines.append({"task": task, "tool": tool})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf8")
    print(f"wrote {len(lines)} seed lines -> {out}")


if __name__ == "__main__":
    main()
