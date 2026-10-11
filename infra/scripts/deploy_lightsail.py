"""Use OIDC-backed AWS credentials to get temporary, host-verified Lightsail SSH access."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def validate_image(image):
    if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Expected a GHCR image digest")
    return image


def secret_payload(environment):
    token = environment.get("DISCORD_TOKEN", "")
    timezone = environment.get("REMINDER_TIMEZONE", "UTC")
    if "\n" in token or "\r" in token:
        raise ValueError("DISCORD_TOKEN must be a single-line token")
    if not re.fullmatch(r"[A-Za-z0-9_+/-]+", timezone):
        raise ValueError("Invalid reminder timezone")
    return json.dumps({
        "Discord_Token": token,
        "REMINDER_TIMEZONE": timezone,
        "GHCR_USERNAME": environment.get("GHCR_USERNAME", ""),
        "GHCR_TOKEN": environment.get("GHCR_TOKEN", ""),
    })


def known_hosts(details):
    address = str(ipaddress.IPv4Address(details["ipAddress"]))
    lines = []
    for host_key in details.get("hostKeys", []):
        algorithm = host_key["algorithm"]
        if algorithm not in {"ssh-rsa", "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}:
            continue
        fields = host_key["publicKey"].split()
        key = fields[1] if len(fields) >= 2 and fields[0] == algorithm else fields[0]
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", key):
            raise ValueError("Malformed Lightsail SSH host key")
        lines.append(f"{address} {algorithm} {key}\n")
    if not lines:
        raise ValueError("Lightsail returned no usable SSH host keys; refusing unverified access")
    return "".join(lines)


def main():
    image = validate_image(os.environ["IMAGE"])
    payload = secret_payload(os.environ)
    instance_name = os.environ["INSTANCE_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", instance_name):
        raise ValueError("Invalid Lightsail instance name")
    details = json.loads(subprocess.check_output([
        "aws", "lightsail", "get-instance-access-details", "--instance-name", instance_name,
        "--protocol", "ssh", "--output", "json",
    ], text=True))["accessDetails"]
    username = details["username"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
        raise ValueError("Invalid SSH username")
    address = str(ipaddress.IPv4Address(details["ipAddress"]))
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        key = directory / "tempkey"
        key.write_text(details["privateKey"])
        key.chmod(0o600)
        (directory / "tempkey-cert.pub").write_text(details["certKey"])
        hosts = directory / "known_hosts"
        hosts.write_text(known_hosts(details))
        subprocess.run([
            "ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={hosts}",
            "-o", "ConnectTimeout=30", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=4", f"{username}@{address}",
            f"sudo /usr/local/bin/aquatidy-deploy '{image}'",
        ], input=payload, text=True, check=True, timeout=1800)


if __name__ == "__main__":
    main()
