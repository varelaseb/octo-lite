from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts/check-traces"
FIXTURES = ROOT / "tests/fixtures/traces"


class TraceContractTests(unittest.TestCase):
    def test_happy_failure_and_retry_fixtures_pass(self) -> None:
        for name in ("happy.jsonl", "failure.jsonl", "retry.jsonl"):
            subprocess.run([str(CHECK), str(FIXTURES / name)], check=True)

    def test_invalid_fixture_fails(self) -> None:
        result = subprocess.run([str(CHECK), str(FIXTURES / "invalid.jsonl")])
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
