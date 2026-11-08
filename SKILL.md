---
name: trace-assay
description: >-
  Before fine-tuning anything on your own agent session traces, freeze an
  imprint card (behaviors to teach, behaviors to refuse) and gate the corpus
  with FIRE / STRIP / HOLD. Sweeps secrets and addresses, drops noise and
  forbidden runs, splits by family so a holdout cannot leak, checks coverage
  per imprint, and emits preference pairs from a success plus a worse attempt.
  Use when you are about to build an SFT or preference set from logs you own,
  not when you want to start a trainer or turn a demo into a SKILL.md.
---

# trace-assay

Session logs look like free training data until a secret, a near-copy, or a failed run quietly enters the mix. **trace-assay** is a pre-train gate: freeze what you want a model to imprint, inspect every trace you are willing to learn from, and refuse to call the batch ready until the holdout is isolated and the secrets are gone.

This skill does **not** launch a training job, merge weights, or write a new skill file from a demo. It answers one question: may this corpus become training data?

## When to use

- You have **session traces you own** (coding-agent logs, support-agent runs, or exported chats) and want to fine-tune or preference-tune a model on them
- You need a machine-checkable answer to “is this batch clean enough to train on?”
- You want **preference pairs** from a good run and a worse attempt of the same job
- You must keep a **frozen holdout** that never sits next to its near-copies in the train split

Do **not** use this to start a hosted trainer, export a GGUF, audit token spend, tidy long-term memory, or turn one demonstrated session into a SKILL.md — those are different jobs.

## Core idea

1. **Imprint card** (frozen once per batch): one goal, the behaviors to imprint, the behaviors to refuse, a split seed, a holdout fraction, a minimum success count per imprint, and a near-duplicate threshold.
2. **Trace**: an id, a **family** (the task or project that must stay on one side of the split), the raw text, an outcome, the imprint ids it demonstrates, and optional `rejected_text` or `refuse_hits`.
3. **Gate** with `scripts/traceassay.py` after you shape the pack and again after every redaction.

### Verdicts

| Verdict | Meaning | Train? |
| --- | --- | --- |
| `FIRE` | Secrets clear, every imprint is covered in train, holdout is isolated | Yes — send only the listed train ids |
| `STRIP` | The batch would be trainable after you remove or redact listed secret traces | No — clean those traces and re-run |
| `HOLD` | Invalid pack, too thin, a single family, or train/holdout leakage | No — collect, reshape, or rewrite |

Exit codes: `0` FIRE, `2` STRIP, `3` HOLD.

## Steps

1. Copy `templates/assay.json` to `assay.json` next to the logs you own.
2. Write one **goal** sentence. List each behavior you want the model to pick up as an imprint (`id` + `title`). List behaviors that must never be learned as `refuse`.
3. Import traces you have the right to use. Give every trace a **family** so two runs of the same task cannot land on both sides of the split.
4. Mark each outcome: `success`, `fail`, `noisy`, `aborted`, or `forbidden`. Attach imprint ids. If you already have a worse attempt of the same job, put it in `rejected_text` or add a `fail` trace in the same family.
5. Tag anything that must not be learned with `refuse_hits` or `outcome: forbidden`.
6. Lint the shape: `python3 scripts/traceassay.py lint assay.json`
7. Run the assay: `python3 scripts/traceassay.py check assay.json`
8. On `STRIP`, redact or drop the listed traces (keys, tokens, emails, password URLs). Do not train “just this once.”
9. On `HOLD`, read the reasons: add successful families, rewrite near-copies that crossed the split, or fix the card.
10. On `FIRE`, train only on the `train` ids. Keep the `holdout` ids untouched — not as few-shot hints, not as smoke prompts. Use emitted `pairs` if you are preference-tuning.

## Pack shape

```json
{
  "card": {
    "goal": "Imprint test-first debugging and cited logs on an in-house coding agent",
    "imprints": [
      {"id": "repro-first", "title": "Reproduce the failing test before editing"},
      {"id": "cite-log", "title": "Cite the log or assertion that proved the fix"}
    ],
    "refuse": [
      {"id": "customer-dump", "title": "Sessions that paste customer records"}
    ],
    "split_seed": 17,
    "holdout_frac": 0.25,
    "min_success_per_imprint": 2,
    "max_near_dup": 0.85
  },
  "traces": [
    {
      "id": "auth-ok",
      "family": "auth",
      "outcome": "success",
      "imprints": ["repro-first", "cite-log"],
      "text": "I reran test_lockout_after_three, read three 401s in the log, then moved the counter increment."
    }
  ]
}
```

Families are ranked by a hash of `split_seed:family`. About `holdout_frac` of them (at least one, and never all) become the holdout. Outcomes `noisy`, `aborted`, and `forbidden` never enter train. Exact duplicates drop. Near-duplicates inside one split drop. Near-duplicates that sit on **both** sides of the split are leaks and force `HOLD`.

The helper scans for private-key blocks, cloud and vendor tokens, bearer headers, JWT-shaped strings, password URLs or assignments, and email addresses. A hit in `text` or `rejected_text` is enough for `STRIP`.

## Examples

**Ready batch** — `examples/debug-fire.json` → `FIRE` (four families, auth also yields two preference pairs).

**Secret still inside** — `examples/debug-strip.json` → `STRIP` when a leftover vendor key and email remain.

**Too thin** — `examples/debug-hold.json` → `HOLD` when `min_success_per_imprint` is higher than train coverage.

**Leaked holdout** — `examples/debug-leak.json` → `HOLD` when a train family restates a holdout trace.

## Tips

- Split by family, never by turn. Two slices of the same session on both sides make every score look better than it is.
- Failures are not free extra rows. Keep them as the rejected side of a pair, or drop them. Do not reward a model for repeating a broken attempt.
- Judge later training runs by behavior on the frozen holdout, not by a falling loss curve.
- The secret scan is a net, not a proof. Read a sample of kept traces yourself before you spend on training.
- Rebuild and re-assay after any redaction. A cleaned file is a new pack.
- No network calls, no API keys. The helper is Python 3 from the standard library.
