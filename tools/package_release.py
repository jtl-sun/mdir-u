"""Package the tested Git commit, excluding untracked local files."""
from pathlib import Path
import hashlib
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from mdir_u import __version__
out = root / "dist"
out.mkdir(exist_ok=True)
archive = out / f"mDIR-U-{__version__}.zip"
subprocess.run(["git", "archive", "--format=zip", f"--prefix=mDIR-U-{__version__}/", "-o", str(archive), "HEAD"], cwd=root, check=True)
files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
(out / "SHA256SUMS.txt").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in files), encoding="utf-8")
