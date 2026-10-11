"""Render the launch script for manual setup of an existing Lightsail instance."""
import argparse
from pathlib import Path
import re


def render(repository):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use owner/repository")
    infra = Path(__file__).resolve().parents[1]
    content = (infra / "cloud-init.sh.tftpl").read_text()
    for name, value in {
        "repository": repository.lower(),
        "backup_script": (infra / "scripts/backup.sh").read_text(),
        "deploy_script": (infra / "scripts/deploy.sh").read_text(),
        "run_script": (infra / "scripts/run.sh").read_text(),
    }.items():
        content = content.replace("${" + name + "}", value)
    return content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="MichaelKema/AquaTidyBot")
    args = parser.parse_args()
    print(render(args.repository), end="")
