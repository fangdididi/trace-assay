#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from traceassay import assay, cmd_check, cmd_demo, cmd_lint, demo_pack, exit_code, validate_pack


def pack_with(**kwargs):
    data = demo_pack()
    data["card"].update(kwargs.pop("card", {}))
    if "traces" in kwargs:
        data["traces"] = kwargs["traces"]
    else:
        extra = kwargs.get("extra_traces") or []
        data["traces"].extend(extra)
    return data


class LintTests(unittest.TestCase):
    def test_demo_pack_is_valid(self):
        self.assertEqual(validate_pack(demo_pack()), [])

    def test_missing_goal(self):
        data = demo_pack()
        data["card"]["goal"] = ""
        errors = validate_pack(data)
        self.assertTrue(any("goal" in item for item in errors))

    def test_duplicate_imprint_ids(self):
        data = demo_pack()
        data["card"]["imprints"].append({"id": "repro-first", "title": "again"})
        errors = validate_pack(data)
        self.assertTrue(any("duplicate" in item for item in errors))

    def test_unknown_imprint_on_trace(self):
        data = demo_pack()
        data["traces"][0]["imprints"] = ["not-a-real-imprint"]
        errors = validate_pack(data)
        self.assertTrue(any("unknown id" in item for item in errors))

    def test_bad_outcome(self):
        data = demo_pack()
        data["traces"][0]["outcome"] = "maybe"
        errors = validate_pack(data)
        self.assertTrue(any("outcome" in item for item in errors))


class AssayTests(unittest.TestCase):
    def test_demo_fires(self):
        result = assay(demo_pack())
        self.assertEqual(result["verdict"], "FIRE")
        self.assertEqual(sorted(result["holdout"]), ["pay-ok"])
        self.assertEqual(sorted(result["train"]), ["auth-ok", "notify-ok", "search-ok"])

    def test_same_family_stays_together(self):
        data = demo_pack()
        twin = dict(data["traces"][1])
        twin["id"] = "auth-ok-2"
        twin["text"] = twin["text"] + " A second successful retry was recorded in the notes."
        data["traces"].append(twin)
        result = assay(data)
        self.assertIn("auth-ok", result["train"])
        self.assertIn("auth-ok-2", result["train"])
        self.assertNotIn("auth-ok-2", result["holdout"])

    def test_strip_vendor_secret_and_email(self):
        data = json.loads((ROOT / "examples" / "debug-strip.json").read_text())
        result = assay(data)
        self.assertEqual(result["verdict"], "STRIP")
        kinds = {hit["kind"] for item in result["secrets"] for hit in item["hits"]}
        self.assertIn("vendor_secret", kinds)
        self.assertIn("email", kinds)

    def test_strip_private_key(self):
        data = demo_pack()
        data["traces"].append(
            {
                "id": "key-leak",
                "family": "pay",
                "outcome": "success",
                "imprints": ["repro-first", "cite-log"],
                "text": "I dumped -----BEGIN RSA PRIVATE KEY----- and kept going.",
            }
        )
        result = assay(data)
        self.assertEqual(result["verdict"], "STRIP")
        self.assertEqual(result["secrets"][0]["hits"][0]["kind"], "private_key")

    def test_hold_when_coverage_thin(self):
        data = json.loads((ROOT / "examples" / "debug-hold.json").read_text())
        result = assay(data)
        self.assertEqual(result["verdict"], "HOLD")
        self.assertTrue(any("coverage" in item for item in result["reasons"]))

    def test_hold_single_family(self):
        data = demo_pack()
        data["traces"] = [data["traces"][0]]
        result = assay(data)
        self.assertEqual(result["verdict"], "HOLD")
        self.assertTrue(any("two families" in item for item in result["reasons"]))

    def test_hold_on_cross_split_leak(self):
        data = json.loads((ROOT / "examples" / "debug-leak.json").read_text())
        result = assay(data)
        self.assertEqual(result["verdict"], "HOLD")
        self.assertEqual(result["leaks"][0]["train"], "notify-ok")
        self.assertEqual(result["leaks"][0]["holdout"], "pay-ok")

    def test_exact_duplicate_dropped(self):
        data = demo_pack()
        clone = dict(data["traces"][2])
        clone["id"] = "search-copy"
        clone["family"] = "other"
        data["traces"].append(clone)
        result = assay(data)
        self.assertTrue(any(item["id"] == "search-copy" and item["reason"] == "duplicate" for item in result["dropped"]))
        self.assertNotIn("search-copy", result["train"] + result["holdout"])

    def test_forbidden_and_noisy_dropped(self):
        data = demo_pack()
        data["traces"].append(
            {
                "id": "dump",
                "family": "pay",
                "outcome": "forbidden",
                "imprints": ["repro-first"],
                "refuse_hits": ["customer-dump"],
                "text": "I pasted a customer roster into the prompt.",
            }
        )
        data["traces"].append(
            {
                "id": "noise",
                "family": "search",
                "outcome": "noisy",
                "imprints": ["cite-log"],
                "text": "The session died mid-tool call and never recovered a result.",
            }
        )
        result = assay(data)
        reasons = {item["id"]: item["reason"] for item in result["dropped"]}
        self.assertEqual(reasons["dump"], "forbidden")
        self.assertEqual(reasons["noise"], "noisy")
        self.assertEqual(result["verdict"], "FIRE")

    def test_preference_pairs_from_fail_and_rejected_text(self):
        data = json.loads((ROOT / "examples" / "debug-fire.json").read_text())
        result = assay(data)
        self.assertEqual(result["verdict"], "FIRE")
        rejected = {(item["chosen"], item["rejected"]) for item in result["pairs"]}
        self.assertIn(("auth-ok", "auth-ok#rejected"), rejected)
        self.assertIn(("auth-ok", "auth-fail"), rejected)

    def test_secret_in_rejected_text_strips(self):
        data = demo_pack()
        data["traces"][1]["rejected_text"] = "I printed the token ghp_abcdefghijklmnopqrstuvwxyz123456 into the log."
        result = assay(data)
        self.assertEqual(result["verdict"], "STRIP")
        self.assertEqual(result["secrets"][0]["id"], "auth-ok")

    def test_invalid_pack_holds(self):
        result = assay({"card": {}, "traces": []})
        self.assertEqual(result["verdict"], "HOLD")
        self.assertTrue(result["reasons"][0].startswith("invalid pack:"))


class CliTests(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual(exit_code("FIRE"), 0)
        self.assertEqual(exit_code("STRIP"), 2)
        self.assertEqual(exit_code("HOLD"), 3)

    def test_lint_and_check_files(self):
        self.assertEqual(cmd_lint(str(ROOT / "examples" / "debug-fire.json")), 0)
        self.assertEqual(cmd_check(str(ROOT / "examples" / "debug-fire.json")), 0)
        self.assertEqual(cmd_check(str(ROOT / "examples" / "debug-strip.json")), 2)
        self.assertEqual(cmd_check(str(ROOT / "examples" / "debug-hold.json")), 3)
        self.assertEqual(cmd_demo(), 0)

    def test_lint_bad_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"card": {"goal": ""}, "traces": []}, handle)
            name = handle.name
        self.assertEqual(cmd_lint(name), 3)


if __name__ == "__main__":
    unittest.main()
