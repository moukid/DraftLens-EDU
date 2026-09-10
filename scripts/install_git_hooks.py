"""Install the repository CAD guard without replacing another hook configuration."""
from pathlib import Path
import subprocess


def install() -> int:
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "-C", str(repo), "config", "--local", "--get", "core.hooksPath"],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        print("Hook setup failed: Git configuration could not be read.")
        return 1
    current = result.stdout.strip()
    if current and current != ".githooks":
        print("Hook setup stopped: another hooksPath is configured. Integrate the CAD guard into it explicitly.")
        return 1
    result = subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", ".githooks"],
                            capture_output=True)
    if result.returncode:
        print("Hook setup failed: Git configuration could not be updated.")
        return 1
    print("CAD pre-commit guard installed for this clone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(install())
