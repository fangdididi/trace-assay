#!/usr/bin/env python3
"""Pre-train assay for agent session traces. Stdlib only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUTCOMES = ("success", "fail", "noisy", "aborted", "forbidden")
DROP_OUTCOMES = {"noisy", "aborted", "forbidden"}

SECRET_SPECS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("github_finegrain", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*")),
    ("vendor_secret", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("password_url", re.compile(r"://[^/\s:]+:[^/\s@]+@")),
    ("password_assign", re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*\S+")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)


def die(msg: str, code: int = 3) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def load_json(path: str) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"HOLD invalid json: {exc}")
    if not isinstance(data, dict):
        die("HOLD pack must be a JSON object")
    return data


def normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def shingles(text: str, n: int = 3) -> set:
    tokens = normalize_text(text).split()
    if not tokens:
        return set()
    if len(tokens) < n:
        return {tuple(tokens)}
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def find_secrets(text: str) -> list[dict]:
    hits = []
    for kind, pat in SECRET_SPECS:
        for match in pat.finditer(text or ""):
            snippet = match.group(0)
            if len(snippet) > 28:
                snippet = snippet[:28] + "…"
            hits.append({"kind": kind, "snippet": snippet})
    return hits


def assign_splits(families: list[str], seed: int, holdout_frac: float) -> dict[str, str]:
    unique = sorted(set(families))
    if len(unique) < 2:
        return {name: "unsplit" for name in unique}
    ranked = sorted(
        unique,
        key=lambda name: hashlib.sha256(f"{seed}:{name}".encode("utf-8")).hexdigest(),
    )
    n_hold = max(1, int(round(len(ranked) * holdout_frac)))
    if n_hold >= len(ranked):
        n_hold = 1
    held = set(ranked[:n_hold])
    return {name: ("holdout" if name in held else "train") for name in unique}


def _as_id_title_list(value, field: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not value:
        if field == "imprints":
            raise ValueError("imprints must be a non-empty list")
        return []
    out = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"each {field} entry must be an object")
        iid = item.get("id")
        title = item.get("title")
        if not isinstance(iid, str) or not iid.strip():
            raise ValueError(f"each {field} entry needs a non-empty id")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"each {field} entry needs a non-empty title")
        if iid in seen:
            raise ValueError(f"duplicate {field} id: {iid}")
        seen.add(iid)
        out.append({"id": iid, "title": title.strip()})
    return out


def validate_pack(data: dict) -> list[str]:
    errors = []
    card = data.get("card")
    if not isinstance(card, dict):
        return ["card must be an object"]
    goal = card.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        errors.append("card.goal must be a non-empty string")
    try:
        imprints = _as_id_title_list(card.get("imprints"), "imprints")
    except ValueError as exc:
        errors.append(str(exc))
        imprints = []
    if not imprints and "imprints must be a non-empty list" not in errors:
        if not card.get("imprints"):
            errors.append("imprints must be a non-empty list")
    try:
        _as_id_title_list(card.get("refuse") or [], "refuse")
    except ValueError as exc:
        errors.append(str(exc))
    seed = card.get("split_seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        errors.append("card.split_seed must be an integer")
    frac = card.get("holdout_frac", 0.25)
    if not isinstance(frac, (int, float)) or isinstance(frac, bool) or not (0 < float(frac) < 0.5):
        errors.append("card.holdout_frac must be a number between 0 and 0.5 (exclusive)")
    minimum = card.get("min_success_per_imprint", 2)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        errors.append("card.min_success_per_imprint must be an integer >= 1")
    near = card.get("max_near_dup", 0.85)
    if not isinstance(near, (int, float)) or isinstance(near, bool) or not (0.5 < float(near) <= 1.0):
        errors.append("card.max_near_dup must be a number in (0.5, 1.0]")

    traces = data.get("traces")
    if not isinstance(traces, list) or not traces:
        errors.append("traces must be a non-empty list")
        return errors

    imprint_ids = {item["id"] for item in imprints}
    refuse_ids = set()
    try:
        refuse_ids = {item["id"] for item in _as_id_title_list(card.get("refuse") or [], "refuse")}
    except ValueError:
        pass
    seen_ids = set()
    for idx, trace in enumerate(traces):
        prefix = f"traces[{idx}]"
        if not isinstance(trace, dict):
            errors.append(f"{prefix} must be an object")
            continue
        tid = trace.get("id")
        if not isinstance(tid, str) or not tid.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        elif tid in seen_ids:
            errors.append(f"duplicate trace id: {tid}")
        else:
            seen_ids.add(tid)
        family = trace.get("family")
        if not isinstance(family, str) or not family.strip():
            errors.append(f"{prefix}.family must be a non-empty string")
        text = trace.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{prefix}.text must be a non-empty string")
        outcome = trace.get("outcome")
        if outcome not in OUTCOMES:
            errors.append(f"{prefix}.outcome must be one of {', '.join(OUTCOMES)}")
        imps = trace.get("imprints")
        if not isinstance(imps, list) or not imps or not all(isinstance(x, str) and x for x in imps):
            errors.append(f"{prefix}.imprints must be a non-empty list of ids")
        else:
            for item in imps:
                if item not in imprint_ids:
                    errors.append(f"{prefix}.imprints unknown id: {item}")
        rejected = trace.get("rejected_text")
        if rejected is not None and (not isinstance(rejected, str) or not rejected.strip()):
            errors.append(f"{prefix}.rejected_text must be a non-empty string when set")
        hits = trace.get("refuse_hits")
        if hits is not None:
            if not isinstance(hits, list) or not all(isinstance(x, str) and x for x in hits):
                errors.append(f"{prefix}.refuse_hits must be a list of ids")
            else:
                for item in hits:
                    if item not in refuse_ids:
                        errors.append(f"{prefix}.refuse_hits unknown id: {item}")
    return errors


def assay(data: dict) -> dict:
    errors = validate_pack(data)
    if errors:
        return {
            "verdict": "HOLD",
            "reasons": [f"invalid pack: {e}" for e in errors],
            "train": [],
            "holdout": [],
            "dropped": [],
            "pairs": [],
            "coverage": {},
            "secrets": [],
            "near_dups": [],
            "leaks": [],
        }

    card = data["card"]
    imprints = _as_id_title_list(card["imprints"], "imprints")
    imprint_ids = [item["id"] for item in imprints]
    seed = card.get("split_seed", 0)
    holdout_frac = float(card.get("holdout_frac", 0.25))
    min_success = int(card.get("min_success_per_imprint", 2))
    max_near = float(card.get("max_near_dup", 0.85))

    secrets: list[dict] = []
    dropped: list[dict] = []
    eligible: list[dict] = []
    seen_hash: dict[str, str] = {}

    for trace in data["traces"]:
        tid = trace["id"]
        family = trace["family"].strip()
        text = trace["text"]
        outcome = trace["outcome"]
        refuse_hits = list(trace.get("refuse_hits") or [])
        secret_hits = find_secrets(text)
        if trace.get("rejected_text"):
            secret_hits.extend(find_secrets(trace["rejected_text"]))
        if secret_hits:
            secrets.append({"id": tid, "hits": secret_hits})
            dropped.append({"id": tid, "reason": "secret"})
            continue
        if refuse_hits or outcome == "forbidden":
            dropped.append({"id": tid, "reason": "forbidden"})
            continue
        if outcome in {"noisy", "aborted"}:
            dropped.append({"id": tid, "reason": outcome})
            continue
        digest = text_hash(text)
        if digest in seen_hash:
            dropped.append({"id": tid, "reason": "duplicate", "of": seen_hash[digest]})
            continue
        seen_hash[digest] = tid
        eligible.append(
            {
                "id": tid,
                "family": family,
                "text": text,
                "outcome": outcome,
                "imprints": list(trace["imprints"]),
                "rejected_text": trace.get("rejected_text"),
                "shingles": shingles(text),
            }
        )

    successes = [item for item in eligible if item["outcome"] == "success"]
    fails = [item for item in eligible if item["outcome"] == "fail"]

    families = [item["family"] for item in successes]
    splits = assign_splits(families, seed, holdout_frac)
    buckets = {"train": [], "holdout": [], "unsplit": []}
    near_dups = []
    for item in successes:
        bucket = splits.get(item["family"], "unsplit")
        item["split"] = bucket
        twin = None
        score = 0.0
        for prev in buckets[bucket]:
            score = jaccard(item["shingles"], prev["shingles"])
            if score >= max_near:
                twin = prev["id"]
                break
        if twin:
            near_dups.append({"id": item["id"], "like": twin, "score": round(score, 3)})
            dropped.append({"id": item["id"], "reason": "near_dup", "of": twin})
            continue
        buckets[bucket].append(item)
    train = buckets["train"]
    holdout = buckets["holdout"]

    leaks = []
    for left in train:
        for right in holdout:
            score = jaccard(left["shingles"], right["shingles"])
            if score >= max_near or text_hash(left["text"]) == text_hash(right["text"]):
                leaks.append(
                    {
                        "train": left["id"],
                        "holdout": right["id"],
                        "score": round(score, 3),
                    }
                )

    coverage = {iid: 0 for iid in imprint_ids}
    for item in train:
        for iid in item["imprints"]:
            if iid in coverage:
                coverage[iid] += 1

    pairs = []
    fails_by_family = defaultdict(list)
    for item in fails:
        fails_by_family[item["family"]].append(item)
    for item in train:
        if item.get("rejected_text"):
            pairs.append(
                {
                    "chosen": item["id"],
                    "rejected": f"{item['id']}#rejected",
                    "family": item["family"],
                    "imprints": item["imprints"],
                }
            )
        for failed in fails_by_family.get(item["family"], []):
            overlap = sorted(set(item["imprints"]) & set(failed["imprints"]))
            if overlap:
                pairs.append(
                    {
                        "chosen": item["id"],
                        "rejected": failed["id"],
                        "family": item["family"],
                        "imprints": overlap,
                    }
                )

    reasons = []
    missing = [iid for iid, count in coverage.items() if count < min_success]
    if not successes:
        reasons.append("no eligible success traces remain")
    if any(item.get("split") == "unsplit" for item in successes) or len(set(families)) < 2:
        reasons.append("need at least two families so a holdout can be split off")
    if successes and not train:
        reasons.append("train split is empty")
    if successes and not holdout and len(set(families)) >= 2:
        reasons.append("holdout split is empty")
    if missing:
        reasons.append(
            "train coverage below min_success_per_imprint for: " + ", ".join(missing)
        )
    if leaks:
        reasons.append(f"{len(leaks)} train/holdout leak(s)")

    if reasons:
        verdict = "HOLD"
    elif secrets:
        verdict = "STRIP"
        reasons.append(f"{len(secrets)} trace(s) still contain secrets or personal addresses")
    else:
        verdict = "FIRE"
        reasons.append("eligible successes cover every imprint, holdout is isolated, secrets are clear")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "train": [item["id"] for item in train],
        "holdout": [item["id"] for item in holdout],
        "dropped": dropped,
        "pairs": pairs,
        "coverage": coverage,
        "secrets": secrets,
        "near_dups": near_dups,
        "leaks": leaks,
        "goal": card["goal"].strip(),
    }


def format_report(result: dict) -> str:
    lines = [result["verdict"]]
    for reason in result["reasons"]:
        lines.append(f"- {reason}")
    if result["coverage"]:
        cov = ", ".join(f"{k}={v}" for k, v in result["coverage"].items())
        lines.append(f"coverage (train successes): {cov}")
    lines.append(f"train: {', '.join(result['train']) or '(none)'}")
    lines.append(f"holdout: {', '.join(result['holdout']) or '(none)'}")
    if result["pairs"]:
        lines.append(f"pairs: {len(result['pairs'])}")
    if result["dropped"]:
        lines.append(f"dropped: {len(result['dropped'])}")
    lines.append(json.dumps(result, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def exit_code(verdict: str) -> int:
    if verdict == "FIRE":
        return 0
    if verdict == "STRIP":
        return 2
    return 3


def cmd_lint(path: str) -> int:
    errors = validate_pack(load_json(path))
    if errors:
        print("HOLD")
        for item in errors:
            print(f"- {item}")
        return 3
    print("OK")
    return 0


def cmd_check(path: str) -> int:
    result = assay(load_json(path))
    print(format_report(result))
    return exit_code(result["verdict"])


def demo_pack() -> dict:
    return {
        "card": {
            "goal": "Imprint test-first debugging and cited logs on an in-house coding agent",
            "imprints": [
                {"id": "repro-first", "title": "Reproduce the failing test before editing"},
                {"id": "cite-log", "title": "Cite the log or assertion that proved the fix"},
            ],
            "refuse": [
                {"id": "customer-dump", "title": "Sessions that paste customer records"}
            ],
            "split_seed": 17,
            "holdout_frac": 0.25,
            "min_success_per_imprint": 2,
            "max_near_dup": 0.85,
        },
        "traces": [
            {
                "id": "pay-ok",
                "family": "pay",
                "outcome": "success",
                "imprints": ["repro-first", "cite-log"],
                "text": (
                    "The billing test test_invoice_total was red. I reran pytest on that file first, "
                    "read the assertion 19.99 versus 20.00, fixed rounding in the invoice helper, "
                    "and reran until the same line passed."
                ),
            },
            {
                "id": "auth-ok",
                "family": "auth",
                "outcome": "success",
                "imprints": ["repro-first", "cite-log"],
                "text": (
                    "Login lockout failed in test_lockout_after_three. I reproduced it with the "
                    "existing fixture, counted the three 401 responses in the captured log, then "
                    "moved the counter increment ahead of the early return."
                ),
            },
            {
                "id": "search-ok",
                "family": "search",
                "outcome": "success",
                "imprints": ["repro-first", "cite-log"],
                "text": (
                    "Highlight search missed stemmed tokens. I ran the stem fixture test, watched "
                    "it expect 'run' to match 'running', updated the analyzer, and pasted the "
                    "passing assertion into the notes."
                ),
            },
            {
                "id": "notify-ok",
                "family": "notify",
                "outcome": "success",
                "imprints": ["repro-first", "cite-log"],
                "text": (
                    "Digest mail skipped weekend hours. I executed test_weekend_skip, confirmed "
                    "the captured cron line fired on Saturday, and narrowed the weekday guard."
                ),
            },
        ],
    }


def cmd_demo() -> int:
    result = assay(demo_pack())
    print(format_report(result))
    return exit_code(result["verdict"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assay agent session traces before they become training data."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_lint = sub.add_parser("lint", help="check pack shape only")
    p_lint.add_argument("pack")
    p_check = sub.add_parser("check", help="run the full assay")
    p_check.add_argument("pack")
    sub.add_parser("demo", help="run the built-in clean pack")
    args = parser.parse_args(argv)
    if args.cmd == "lint":
        return cmd_lint(args.pack)
    if args.cmd == "check":
        return cmd_check(args.pack)
    if args.cmd == "demo":
        return cmd_demo()
    return 3


if __name__ == "__main__":
    sys.exit(main())
