"""Plan and record the publication of per-profile models.

A model may be published only when the file about to be uploaded is byte-for-byte the file that was
evaluated (sha256 recorded by eval_profiles.sh) and its scores pass the gate against that profile's
own baseline. The manifest it produces lets an installer pick and verify a model by profile id.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import gate

BASE_MODEL = {
    "name": "needle3",
    "source": "https://huggingface.co/Cactus-Compute/needle3",
    "revision": "d6c7d6a2e9655505e0f8e23339356dd1705900eb",
    "license": "Apache-2.0",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(
    models_dir: Path,
    profiles: list[str],
    root: Path,
    tag: str,
    public_repo: str,
    system_mode: str = "profile",
    git_sha: str = "",
    catalog_sha: str = "",
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (plan, problems). A plan exists only when every requested profile is publishable."""
    suffix = ".nosystem" if system_mode == "none" else ""
    problems: list[str] = []
    entries: list[dict[str, Any]] = []
    for p in profiles:
        cact = models_dir / f"hela-needle3-{p}.cact"
        cand = root / "eval" / "candidates" / f"{p}{suffix}.json"
        cand_sha = root / "eval" / "candidates" / f"{p}{suffix}.sha256"
        base = root / "eval" / "baselines" / f"{p}{suffix}.json"
        missing = [str(x.relative_to(root)) if x.is_relative_to(root) else str(x) for x in (cact, cand, cand_sha, base) if not x.exists()]
        if missing:
            problems.append(f"{p}: missing {', '.join(missing)}")
            continue
        sha = sha256_file(cact)
        evaluated = cand_sha.read_text().split()[0]
        if sha != evaluated:
            problems.append(f"{p}: the file to publish is not the file that was evaluated (sha256 differs)")
            continue
        scores = json.loads(cand.read_text())
        baseline = json.loads(base.read_text())
        reasons = gate.check(scores, baseline)
        if reasons:
            problems.append(f"{p}: gate fails: " + "; ".join(reasons))
            continue
        meta_path = models_dir / f"meta-{p}.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        file_name = cact.name
        entries.append({
            "profile": p,
            "file": file_name,
            "url": f"https://github.com/{public_repo}/releases/download/{tag}/{file_name}",
            "sha256": sha,
            "size": cact.stat().st_size,
            "system_mode": system_mode,
            "base": BASE_MODEL,
            "trained_on": {
                "repo_commit": git_sha,
                "catalog_sha256": catalog_sha,
                "train_rows": meta.get("train_rows"),
                "eval_rows": meta.get("eval_rows"),
                "epochs": meta.get("epochs"),
            },
            "scores": {"candidate": scores, "baseline": baseline},
            "release": tag,
        })
    if problems:
        return None, problems
    return {"tag": tag, "entries": entries}, []


def apply_manifest(manifest_path: Path, the_plan: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace one entry per profile; other profiles are kept."""
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {"schema": 1, "base": BASE_MODEL, "models": {}}
    for entry in the_plan["entries"]:
        manifest["models"][entry["profile"]] = entry
    manifest["models"] = dict(sorted(manifest["models"].items()))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    return manifest
