"""Check actual-binary observations and rejection of stale or ambiguous metadata."""

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("terraform_toolchain", ROOT / "scripts/check-terraform-toolchain.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
BINARY = Path("/synthetic/terraform")


def metadata(binary=BINARY, go="go1.26.10", arch="arm64"):
    return (f"{binary}: {go}\n\tpath\tgithub.com/hashicorp/terraform\n"
            f"\tbuild\tGOOS=linux\n\tbuild\tGOARCH={arch}\n")


class TerraformToolchainTests(unittest.TestCase):
    def validate(self, version="1.17.0", go="go1.26.10", platform="linux_arm64", machine="aarch64", text=None):
        return CHECK.validate_observations({"terraform_version": version, "platform": platform},
                                          metadata(go=go) if text is None else text,
                                          BINARY, "linux_arm64", "Linux", machine)

    def test_supported_patched_go_lines_and_future_stable_minor_pass(self):
        for go in ("go1.26.10", "go1.26.11", "go1.27.3", "go1.28.0"):
            self.assertEqual(self.validate(go=go)["embedded_go_version"], go)

    def test_terraform_downgrade_and_prerelease_fail(self):
        for version in ("1.16.7", "1.13.4", "1.17.0-rc1", "1.17.0+local", 117):
            with self.subTest(version=version), self.assertRaises(CHECK.ToolchainError):
                self.validate(version=version)

    def test_old_go_lines_and_prerelease_fail(self):
        for go in ("go1.26.9", "go1.27.2", "go1.25.99", "go1.27rc3", "devel go1.28", "go2.0.0"):
            with self.subTest(go=go), self.assertRaises(CHECK.ToolchainError):
                self.validate(go=go)

    def test_target_and_native_host_must_both_be_arm64(self):
        for values in ({"platform": "linux_amd64"}, {"machine": "x86_64"}):
            with self.subTest(values=values), self.assertRaises(CHECK.ToolchainError):
                self.validate(**values)

    def test_go_metadata_must_be_for_same_binary_and_terraform_main(self):
        for text in (metadata(binary=Path("/other/terraform")),
                     metadata().replace("github.com/hashicorp/terraform", "example.invalid/other"),
                     "unrecognized binary", metadata().replace("GOOS=linux", "GOOS=darwin")):
            with self.subTest(text=text), self.assertRaises(CHECK.ToolchainError):
                self.validate(text=text)

    def test_go_build_architecture_and_duplicate_fields_fail(self):
        for text in (metadata(arch="amd64"), metadata() + "\tbuild\tGOARCH=arm64\n"):
            with self.assertRaises(CHECK.ToolchainError):
                self.validate(text=text)
        with self.assertRaises(CHECK.ToolchainError):
            json.loads('{"platform":"linux_arm64","platform":"linux_amd64"}', object_pairs_hook=CHECK.unique_object)

    def test_observer_executes_and_hashes_the_exact_metadata_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "terraform"
            binary.write_bytes(b"synthetic compiler fixture")
            responses = [json.dumps({"terraform_version": "1.17.0", "platform": "linux_arm64"}), metadata(binary)]
            with patch.object(CHECK.shutil, "which", side_effect=lambda name: str(binary) if name == "terraform" else "/usr/bin/go"), \
                    patch.object(CHECK.platform, "system", return_value="Linux"), \
                    patch.object(CHECK.platform, "machine", return_value="aarch64"), \
                    patch.object(CHECK, "command", side_effect=responses) as command:
                result = CHECK.observe("linux_arm64")
            self.assertEqual(command.call_args_list[0].args[0], [str(binary), "version", "-json"])
            self.assertEqual(command.call_args_list[1].args[0], ["/usr/bin/go", "version", "-m", str(binary)])
            self.assertEqual(result["terraform_binary_sha256"], hashlib.sha256(binary.read_bytes()).hexdigest())

    def test_binary_changed_during_metadata_observation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "terraform"
            binary.write_bytes(b"synthetic compiler fixture")
            def run(args):
                if "-json" in args:
                    return json.dumps({"terraform_version": "1.17.0", "platform": "linux_arm64"})
                binary.write_bytes(b"changed compiler fixture")
                return metadata(binary)
            with patch.object(CHECK.shutil, "which", side_effect=lambda name: str(binary) if name == "terraform" else "/usr/bin/go"), \
                    patch.object(CHECK.platform, "system", return_value="Linux"), \
                    patch.object(CHECK.platform, "machine", return_value="aarch64"), patch.object(CHECK, "command", side_effect=run):
                with self.assertRaisesRegex(CHECK.ToolchainError, "terraform_binary_changed"):
                    CHECK.observe("linux_arm64")

    def test_no_checkpoint_or_go_downloads_are_permitted(self):
        response = SimpleNamespace(returncode=0, stdout="synthetic metadata", stderr="")
        with patch.object(CHECK.subprocess, "run", return_value=response) as run:
            CHECK.command(["terraform", "version", "-json"])
        env = run.call_args.kwargs["env"]
        self.assertEqual({key: env[key] for key in ("CHECKPOINT_DISABLE", "GOTOOLCHAIN", "GOENV", "GOWORK", "GOPROXY", "GOSUMDB")},
                         {"CHECKPOINT_DISABLE": "1", "GOTOOLCHAIN": "local", "GOENV": "off", "GOWORK": "off", "GOPROXY": "off", "GOSUMDB": "off"})

    def test_subprocess_failure_timeout_and_oversize_are_redacted(self):
        for response in (SimpleNamespace(returncode=1, stdout="synthetic private detail", stderr="synthetic private detail"),
                         SimpleNamespace(returncode=0, stdout="x" * (CHECK.MAX_OUTPUT + 1), stderr="")):
            with patch.object(CHECK.subprocess, "run", return_value=response), self.assertRaisesRegex(CHECK.ToolchainError, "^toolchain_observation_failed$"):
                CHECK.command(["synthetic"])
        with patch.object(CHECK.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic private detail", 20)), \
                self.assertRaisesRegex(CHECK.ToolchainError, "^toolchain_observation_failed$"):
            CHECK.command(["synthetic"])

    def test_cli_never_prints_unexpected_raw_errors(self):
        output = io.StringIO()
        with patch.object(CHECK, "observe", side_effect=OSError("synthetic private detail")), redirect_stdout(output):
            self.assertEqual(CHECK.main([]), 1)
        self.assertNotIn("private detail", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["code"], "toolchain_observation_failed")


if __name__ == "__main__":
    unittest.main()
