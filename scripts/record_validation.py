"""Run infrastructure tests and preserve the real process output and summary."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
evidence = root / "evidence"
evidence.mkdir(exist_ok=True)
command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
started = datetime.now(timezone.utc).isoformat()
clock = time.monotonic()
result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
output = result.stdout + result.stderr
(evidence / "infrastructure-tests.txt").write_text(output, encoding="utf-8")
counts = re.findall(r"Ran (\d+) tests? in", output)
summary = {"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
           "command": command, "cwd": str(root), "elapsed_seconds": round(time.monotonic() - clock, 3),
           "exit_code": result.returncode, "tests_run": int(counts[-1]) if counts else None,
           "passed": result.returncode == 0, "output_file": "infrastructure-tests.txt",
           "output_sha256": hashlib.sha256((evidence / "infrastructure-tests.txt").read_bytes()).hexdigest(),
           "provenance": "actual_qasc_infrastructure_test_execution",
           "model_fixtures": "Scripted/loopback fixtures in infrastructure tests; live Qwen evidence is separate"}
(evidence / "infrastructure-tests.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(output, end="")
print(json.dumps(summary, indent=2))
raise SystemExit(result.returncode)
