"""Protocol 29 Testnet and Futurenet verification-record separation."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORDS = REPO_ROOT / "protocol-29" / "verification"


class Protocol29PassphraseRecordTests(unittest.TestCase):
    def run_validator(self, evidence: list[Path]) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(REPO_ROOT / "tools" / "validate" / "validate.py"),
            "protocol-29",
        ]
        for path in evidence:
            command.extend(["--evidence", str(path)])
        return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)

    def test_records_are_valid_and_keep_network_passphrases_distinct(self) -> None:
        testnet = RECORDS / "testnet" / "p29-rpc-network-mismatch.json"
        futurenet = RECORDS / "futurenet" / "p29-rpc-network-mismatch.json"
        testnet_record = json.loads(testnet.read_text(encoding="utf-8"))
        futurenet_record = json.loads(futurenet.read_text(encoding="utf-8"))
        self.assertEqual(testnet_record["network"]["passphrase"], "Test SDF Network ; September 2015")
        self.assertEqual(futurenet_record["network"]["passphrase"], "Test SDF Future Network ; October 2022")
        self.assertEqual(testnet_record["network"]["observedProtocol"], 29)
        self.assertEqual(futurenet_record["network"]["observedProtocol"], 29)

        run = self.run_validator([testnet, futurenet])
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)

    def test_swapped_passphrases_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            copied = []
            for network in ("testnet", "futurenet"):
                source = RECORDS / network / "p29-rpc-network-mismatch.json"
                target = root / f"{network}.json"
                shutil.copyfile(source, target)
                copied.append(target)

            testnet = json.loads(copied[0].read_text(encoding="utf-8"))
            futurenet = json.loads(copied[1].read_text(encoding="utf-8"))
            testnet["network"]["passphrase"], futurenet["network"]["passphrase"] = (
                futurenet["network"]["passphrase"],
                testnet["network"]["passphrase"],
            )
            copied[0].write_text(json.dumps(testnet), encoding="utf-8")
            copied[1].write_text(json.dumps(futurenet), encoding="utf-8")

            run = self.run_validator(copied)
        self.assertEqual(run.returncode, 1)
        self.assertIn("network.passphrase does not match network.name", run.stderr)


if __name__ == "__main__":
    unittest.main()