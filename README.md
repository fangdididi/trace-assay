# trace-assay

[中文](README.zh-CN.md) | **English**

A **pre-train assay for agent session traces**. Freeze an imprint card (what to teach, what to refuse), sweep secrets and addresses, split by family so the holdout cannot leak, require coverage for every imprint, and emit preference pairs — then gate the batch with `FIRE` / `STRIP` / `HOLD`.

This skill does not start a trainer or write a new skill from a demo. It tells you whether a corpus you own is fit to become training data.

## Features

- **Imprint card** — one goal, behaviors to imprint, behaviors to refuse, split seed, holdout fraction, coverage floor
- **Family-aware split** — two runs of the same task stay on the same side; at least one family is held out
- **Secret sweep** — private keys, vendor and cloud tokens, bearer headers, JWT-shaped strings, password URLs, emails
- **Quality drops** — noisy, aborted, and forbidden traces never enter train; exact duplicates and same-split near-duplicates are removed
- **Leak check** — a near-copy that lands in both train and holdout forces `HOLD`
- **Preference pairs** — a success plus `rejected_text`, or a `fail` in the same family that shares an imprint
- **Stdlib helper** — `scripts/traceassay.py` (`lint` / `check` / `demo`) plus unit tests

## Install

```bash
git clone https://github.com/fangdididi/trace-assay.git
cd trace-assay
```

### Claude Code / Codex / Cursor-style agents

- Place or symlink the repo where your agent loads skills from, **or**
- Open the folder and say: “Follow SKILL.md (trace-assay) before we fine-tune on these session logs.”

No API keys. The helper is Python 3 from the standard library.

## Usage

```bash
# shape check
python3 scripts/traceassay.py lint templates/assay.json

# full assay
python3 scripts/traceassay.py check examples/debug-fire.json
python3 scripts/traceassay.py check examples/debug-strip.json
python3 scripts/traceassay.py check examples/debug-hold.json
python3 scripts/traceassay.py check examples/debug-leak.json

# built-in clean pack
python3 scripts/traceassay.py demo

# tests
python3 -m unittest discover -s tests -v
```

Typical agent flow:

1. Fill `assay.json` with an imprint card and traces you own.
2. `lint`, then `check`, and branch on `FIRE` / `STRIP` / `HOLD`.
3. On `FIRE`, train only on the listed `train` ids and leave `holdout` untouched.

## Examples

| File | Expected |
| --- | --- |
| `examples/debug-fire.json` | `FIRE` (with two preference pairs) |
| `examples/debug-strip.json` | `STRIP` (vendor key + email) |
| `examples/debug-hold.json` | `HOLD` (coverage floor not met) |
| `examples/debug-leak.json` | `HOLD` (train restates a holdout trace) |

## File structure

```
trace-assay/
├── SKILL.md
├── SKILL.zh-CN.md
├── README.md
├── README.zh-CN.md
├── LICENSE
├── scripts/traceassay.py
├── templates/assay.json
├── examples/
└── tests/test_traceassay.py
```

## License

MIT © fangdididi
