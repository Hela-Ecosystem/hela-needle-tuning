"""Command line: build-data, check-secrets, eval, gate, export-tools."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import evalrun, gate
from .catalog import load_catalog
from .examples import build_rows, dedupe
from .generated import convert
from .scrub import findings


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf8").splitlines() if ln.strip()]


def cmd_build(a: argparse.Namespace) -> int:
    catalog = load_catalog(a.catalog, a.name_style, a.cells)
    rows: list[dict] = []
    for seed in sorted(Path(a.seeds).glob("*.jsonl")):
        rows += build_rows(seed, catalog, a.seed)
    rows = dedupe(rows)
    out = Path(a.out)
    train = [r for r in rows if r["meta"]["split"] == "train"]
    held = [r for r in rows if r["meta"]["split"] == "eval"]
    # Cactus reads query/tools/answers; meta stays in the eval file for scoring only.
    _write_jsonl(out / "train.jsonl", [{k: r[k] for k in ("query", "tools", "answers")} for r in train])
    _write_jsonl(out / "eval.jsonl", held)
    print(f"catalog={len(catalog)} tools, train={len(train)}, eval={len(held)} rows -> {out}")
    return 0


def cmd_import(a: argparse.Namespace) -> int:
    catalog = load_catalog(a.catalog, a.name_style, a.cells)
    rows: list[dict] = []
    for path in a.inputs:
        rows += _read_jsonl(Path(path))
    seeds, rejected = convert(rows, catalog)
    for seed in seeds:
        seed["note"] = a.source
    _write_jsonl(Path(a.out), seeds)
    print(f"read {len(rows)} rows -> kept {len(seeds)} seed lines in {a.out}")
    for reason, n in rejected.most_common():
        print(f"  rejected {n}: {reason}")
    return 0


def cmd_secrets(a: argparse.Namespace) -> int:
    bad = 0
    for path in a.files:
        for no, line in enumerate(Path(path).read_text(encoding="utf8").splitlines(), 1):
            hits = findings(line)
            if hits:
                bad += 1
                print(f"{path}:{no}: {', '.join(hits)}")
    print("clean" if not bad else f"{bad} line(s) need scrubbing")
    return 1 if bad else 0


def cmd_eval(a: argparse.Namespace) -> int:
    rows = _read_jsonl(Path(a.eval))
    details: list[dict] | None = [] if a.details else None
    scores = evalrun.evaluate(rows, lambda r: evalrun.run_engine(a.engine, a.model, a.system, r, a.timeout), details)
    if details is not None:
        _write_jsonl(Path(a.details), details)
    Path(a.out).write_text(json.dumps(scores, indent=2) + "\n", encoding="utf8")
    print(json.dumps(scores, indent=2))
    return 0


def cmd_gate(a: argparse.Namespace) -> int:
    cand = json.loads(Path(a.candidate).read_text(encoding="utf8"))
    base = json.loads(Path(a.baseline).read_text(encoding="utf8"))
    reasons = gate.check(cand, base, a.min_gain)
    for r in reasons:
        print(f"BLOCK: {r}")
    print("PASS" if not reasons else "FAIL")
    return 1 if reasons else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hela-needle")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-data", help="expand seeds into train/eval jsonl")
    b.add_argument("--catalog", required=True)
    b.add_argument("--seeds", default="data/seed")
    b.add_argument("--out", default="data/build")
    b.add_argument("--name-style", default="qualified", choices=["qualified", "bare"])
    b.add_argument("--cells", nargs="*")
    b.add_argument("--seed", type=int, default=7)
    b.set_defaults(fn=cmd_build)
    i = sub.add_parser("import-generated", help="convert `cactus generate-data` output into validated seed lines")
    i.add_argument("inputs", nargs="+")
    i.add_argument("--catalog", required=True)
    i.add_argument("--cells", nargs="*")
    i.add_argument("--name-style", default="qualified", choices=["qualified", "bare"])
    i.add_argument("--source", default="generated", help="provenance label stored on every line")
    i.add_argument("--out", required=True)
    i.set_defaults(fn=cmd_import)
    s = sub.add_parser("check-secrets", help="fail if any file contains something that must be scrubbed")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_secrets)
    e = sub.add_parser("eval", help="score an engine + weights on eval.jsonl")
    e.add_argument("--eval", default="data/build/eval.jsonl")
    e.add_argument("--engine", required=True)
    e.add_argument("--model")
    e.add_argument("--system")
    e.add_argument("--timeout", type=float, default=30.0)
    e.add_argument("--out", required=True)
    e.add_argument("--details", help="also write one JSON line per row (task, expected, got) for error analysis")
    e.set_defaults(fn=cmd_eval)
    g = sub.add_parser("gate", help="compare candidate scores with the baseline")
    g.add_argument("--candidate", required=True)
    g.add_argument("--baseline", default="eval/baseline.json")
    g.add_argument("--min-gain", type=float, default=gate.MIN_GAIN)
    g.set_defaults(fn=cmd_gate)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
