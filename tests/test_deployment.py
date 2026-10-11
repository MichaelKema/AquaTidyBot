import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("deploy_lightsail", Path(__file__).resolve().parents[1] / "infra/scripts/deploy_lightsail.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
IMAGE = "ghcr.io/michaelkema/aquatidybot@sha256:" + "a" * 64


class DeploymentTests(unittest.TestCase):
    def test_rejects_mutable_images_and_shell_injection(self):
        for image in ("ghcr.io/michaelkema/aquatidybot:latest", IMAGE + "'; echo bad", "-oProxyCommand=bad"):
            with self.subTest(image=image), self.assertRaises(ValueError):
                deploy.validate_image(image)
        self.assertEqual(deploy.validate_image(IMAGE), IMAGE)

    def test_requires_single_line_token(self):
        for token in ("token\nOTHER=value", "token\r"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                deploy.secret_payload({"DISCORD_TOKEN": token})

    def test_empty_token_allows_host_token_reuse(self):
        self.assertEqual(json.loads(deploy.secret_payload({}))["Discord_Token"], "")

    def test_missing_host_keys_fail_closed(self):
        with self.assertRaises(ValueError):
            deploy.known_hosts({"ipAddress": "192.0.2.1", "hostKeys": []})

    def test_verified_ssh_receives_secrets_only_on_stdin(self):
        environment = {
            "INSTANCE_NAME": "aquatidy", "IMAGE": IMAGE,
            "DISCORD_TOKEN": "private-discord-value", "REMINDER_TIMEZONE": "America/New_York",
        }
        details = {
            "username": "ubuntu", "ipAddress": "192.0.2.1", "privateKey": "temporary-key",
            "certKey": "temporary-certificate",
            "hostKeys": [{"algorithm": "ssh-ed25519", "publicKey": "ssh-ed25519 AAAATEST="}],
        }

        def check_ssh(arguments, **kwargs):
            self.assertIn("StrictHostKeyChecking=yes", arguments)
            self.assertNotIn(environment["DISCORD_TOKEN"], " ".join(arguments))
            self.assertEqual(json.loads(kwargs["input"])["Discord_Token"], environment["DISCORD_TOKEN"])
            self.assertTrue(kwargs["check"])
            key = Path(arguments[arguments.index("-i") + 1])
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertTrue(key.with_name("tempkey-cert.pub").exists())
            self.assertEqual(key.with_name("known_hosts").read_text(), "192.0.2.1 ssh-ed25519 AAAATEST=\n")

        with patch.dict(deploy.os.environ, environment, clear=True), \
             patch.object(deploy.subprocess, "check_output", return_value=json.dumps({"accessDetails": details})), \
             patch.object(deploy.subprocess, "run", side_effect=check_ssh) as ssh:
            deploy.main()
        ssh.assert_called_once()


class RolloutTests(unittest.TestCase):
    """Exercise the real rollout script with isolated disk paths and fake host services."""
    def run_rollout(self, failure, token="new-token"):
        import os
        import shutil
        import subprocess
        import tempfile
        if not shutil.which("jq"):
            self.skipTest("jq is required to exercise the rollout script")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            state.mkdir()
            (state / "data").mkdir()
            (state / "image").write_text("old-image\n")
            (state / "bot.env").write_text("Discord_Token=old-token\n")
            (root / "aquatidy-ready").touch()
            (root / "config.json").write_text('{"repository":"michaelkema/aquatidybot"}')
            script = (Path(__file__).resolve().parents[1] / "infra/scripts/deploy.sh").read_text()
            script = script.replace("/var/lib/aquatidy", str(state)).replace("/run/aquatidy", str(root / "aquatidy")).replace("/etc/aquatidy.json", str(root / "config.json"))
            script_path = root / "deploy.sh"
            script_path.write_text(script)
            binaries = root / "bin"
            binaries.mkdir()
            commands = {
                "sleep": "exit 0",
                "mountpoint": "exit 0",
                "flock": "exit 0",
                "docker": '''
if [ "$1" = pull ] && [ "$FAILURE" = pull ]; then exit 1; fi
if [ "$1" = inspect ]; then echo true; fi
exit 0
''',
                "systemctl": '''
printf '%s\\n' "$*" >> "$SERVICE_LOG"
if [ "$1" = is-active ] && [ "$FAILURE" = startup ]; then exit 1; fi
if [ "$1" = show ]; then echo 0; fi
exit 0
''',
            }
            for name, content in commands.items():
                binary = binaries / name
                binary.write_text("#!/bin/bash\n" + content + "\n")
                binary.chmod(0o700)
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                               FAILURE=failure, SERVICE_LOG=str(root / "service.log"))
            result = subprocess.run(["bash", str(script_path), IMAGE],
                                    input=deploy.secret_payload({"DISCORD_TOKEN": token}),
                                    text=True, capture_output=True, env=environment)
            service_log = (root / "service.log").read_text() if (root / "service.log").exists() else ""
            return result.returncode, (state / "image").read_text(), (state / "bot.env").read_text(), service_log

    def test_pull_failure_does_not_stop_current_bot(self):
        code, image, env, log = self.run_rollout("pull")
        self.assertNotEqual(code, 0)
        self.assertEqual(image, "old-image\n")
        self.assertEqual(env, "Discord_Token=old-token\n")
        self.assertEqual(log, "")

    def test_startup_failure_restores_old_image_and_token(self):
        code, image, env, log = self.run_rollout("startup")
        self.assertNotEqual(code, 0)
        self.assertEqual(image, "old-image\n")
        self.assertEqual(env, "Discord_Token=old-token\n")
        self.assertEqual(log.count("start aquatidy\n"), 2)

    def test_success_switches_to_digest_and_new_token(self):
        code, image, env, log = self.run_rollout("")
        self.assertEqual(code, 0)
        self.assertEqual(image, IMAGE + "\n")
        self.assertEqual(env, "Discord_Token=new-token\nREMINDER_TIMEZONE=UTC\n")
        self.assertEqual(log.count("start aquatidy\n"), 1)


    def test_existing_host_token_is_reused_when_ci_secret_is_unset(self):
        code, image, env, log = self.run_rollout("", token="")
        self.assertEqual(code, 0)
        self.assertEqual(env, "Discord_Token=old-token\nREMINDER_TIMEZONE=UTC\n")
