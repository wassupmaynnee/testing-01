"""
Secret scanner — pattern + entropy scan of tracked files, plus git-history scan.

Used two ways:
  * CI gate:  python scripts/secret_scan.py            (exit 1 on tracked findings)
  * Audit:    python scripts/secret_scan.py --history  (also walks git history)

Never prints full secret values — findings show file/line/type and a masked
snippet only. Placeholders (<FILL_ME>, sk_test_..., whsec_xxx docs examples,
*_example values) are allowlisted.

GPL-3.0-only.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    ("stripe_live_key", re.compile(r"sk_live_[A-Za-z0-9]{16,}")),
    ("stripe_test_key", re.compile(r"sk_test_[A-Za-z0-9]{16,}")),
    ("stripe_restricted", re.compile(r"rk_(live|test)_[A-Za-z0-9]{16,}")),
    ("stripe_webhook_secret", re.compile(r"whsec_[A-Za-z0-9_]{10,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("private_key_block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("conn_string_with_pw", re.compile(r"(postgres(ql)?(\+\w+)?|mysql|mongodb|redis)://[^:/\s]+:[^@\s]{6,}@")),
    ("jwt_like", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
]

# Legitimate placeholder/docs values — never findings.
ALLOW = re.compile(
    r"<FILL_ME|whsec_x{4,}|whsec_\.\.\.|sk_live_\.\.\.|sk_test_\.\.\.|sk_live_…|sk_test_…|"
    r"whsec_test_secret|\$\{[A-Z_]+(:-[^}]*)?\}|"  # documented test dummy + compose ${VAR:-default} interpolation
    r"whsec_…|example|placeholder|redacted|clippify:clippify@|user:pass@|:pass@|YOUR_|changeme|change-me",
    re.IGNORECASE,
)

SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "__pycache__", "data", ".ruff_cache"}
SKIP_EXT = {".mp4", ".jpg", ".jpeg", ".png", ".svg", ".ico", ".wav", ".onnx", ".zip", ".gz", ".pyc"}
# The scanner must not flag its own pattern definitions.
SELF = {"scripts/secret_scan.py"}


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


def _mask(m: str) -> str:
    return m[:10] + "…" + f"(len {len(m)})"


def scan_text(text: str, origin: str, findings: list) -> None:
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW.search(line):
            continue
        for name, pat in PATTERNS:
            for m in pat.finditer(line):
                findings.append((origin, lineno, name, _mask(m.group(0))))
        # entropy: long unbroken tokens that look like credentials in assignments
        if re.search(r"(secret|token|password|api_?key)\s*[=:]", line, re.IGNORECASE):
            for tok in re.findall(r"['\"]([A-Za-z0-9+/_=-]{28,})['\"]", line):
                if _entropy(tok) > 4.2:
                    findings.append((origin, lineno, "high_entropy_assignment", _mask(tok)))


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f]


def main() -> int:
    findings: list = []
    for f in tracked_files():
        p = Path(f)
        if f in SELF or p.suffix.lower() in SKIP_EXT or any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            scan_text(p.read_text(encoding="utf-8", errors="ignore"), f, findings)
        except OSError:
            continue

    history_findings: list = []
    if "--history" in sys.argv:
        log = subprocess.run(["git", "log", "--all", "-p", "--no-color"],
                             capture_output=True, text=True, errors="ignore")
        commit = "?"
        for line in log.stdout.splitlines():
            if line.startswith("commit "):
                commit = line.split()[1][:10]
                continue
            if not line.startswith("+") or line.startswith("+++") or ALLOW.search(line):
                continue
            for name, pat in PATTERNS:
                for m in pat.finditer(line):
                    history_findings.append((commit, name, _mask(m.group(0))))

    print("| Location | Line | Type | Masked value |")
    print("|---|---|---|---|")
    for f, ln, name, masked in findings:
        print(f"| {f} | L{ln} | {name} | `{masked}` |")
    if not findings:
        print("| (tracked files clean) | – | – | – |")
    if "--history" in sys.argv:
        print("\n| Commit | Type | Masked value | Status |")
        print("|---|---|---|---|")
        seen = set()
        for c, name, masked in history_findings:
            if (c, name, masked) in seen:
                continue
            seen.add((c, name, masked))
            print(f"| {c} | {name} | `{masked}` | COMPROMISED — ROTATE |")
        if not history_findings:
            print("| (git history clean) | – | – | – |")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
