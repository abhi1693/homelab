#!/usr/bin/env python3
"""Observe the actual native Terraform binary and its embedded Go security floor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess


TERRAFORM_MINIMUM = (1, 17, 0)
GO_MINIMUM = {26: 10, 27: 3}
PLATFORMS = {"linux_arm64": {"aarch64", "arm64"}, "linux_amd64": {"x86_64", "amd64"}}
MAX_OUTPUT = 65536


class ToolchainError(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ToolchainError(code)


def stable_version(value: object, prefix: str = "") -> tuple[int, int, int]:
    match = re.fullmatch(re.escape(prefix) + r"(\d+)\.(\d+)\.(\d+)", value) if isinstance(value, str) else None
    require(match is not None, "stable_toolchain_version_required")
    return tuple(map(int, match.groups()))


def validate_observations(version: dict, build_info: str, binary: Path, expected_platform: str,
                          system: str, machine: str) -> dict:
    require(isinstance(version, dict), "invalid_terraform_version_output")
    require(stable_version(version.get("terraform_version")) >= TERRAFORM_MINIMUM,
            "terraform_below_security_floor")
    require(version.get("platform") == expected_platform, "unexpected_terraform_platform")
    require(system == "Linux" and machine.lower() in PLATFORMS[expected_platform],
            "native_platform_mismatch")
    lines = build_info.splitlines()
    prefix = str(binary) + ": "
    require(bool(lines) and lines[0].startswith(prefix), "go_metadata_binary_mismatch")
    go_version = lines[0][len(prefix):]
    major, minor, patch = stable_version(go_version, "go")
    require(major == 1 and (minor > 27 or minor in GO_MINIMUM and patch >= GO_MINIMUM[minor]),
            "embedded_go_below_security_floor")
    require(lines.count("\tpath\tgithub.com/hashicorp/terraform") == 1,
            "unexpected_go_main_package")
    for key, expected in (("GOOS", "linux"), ("GOARCH", expected_platform.split("_", 1)[1])):
        values = [line.split("=", 1)[1] for line in lines if line.startswith("\tbuild\t" + key + "=")]
        require(values == [expected], "go_build_platform_mismatch")
    return {"terraform_version": version["terraform_version"], "platform": expected_platform,
            "embedded_go_version": go_version, "go_main_package": "github.com/hashicorp/terraform",
            "native_machine": machine, "native_execution": True}


def command(args: list[str]) -> str:
    env = dict(os.environ, CHECKPOINT_DISABLE="1", GOTOOLCHAIN="local", GOENV="off",
               GOWORK="off", GOPROXY="off", GOSUMDB="off")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20,
                                check=False, env=env)
    except Exception:
        raise ToolchainError("toolchain_observation_failed") from None
    require(result.returncode == 0 and len(result.stdout) <= MAX_OUTPUT
            and len(result.stderr) <= MAX_OUTPUT, "toolchain_observation_failed")
    return result.stdout


def fingerprint(path: Path) -> tuple:
    info = path.stat()
    require(path.is_file() and 0 < info.st_size <= 256 * 1024 * 1024, "invalid_terraform_binary")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_toolchain_field")
        result[key] = value
    return result


def observe(expected_platform: str) -> dict:
    terraform = shutil.which("terraform")
    go = shutil.which("go")
    require(bool(terraform) and bool(go), "terraform_and_go_metadata_reader_required")
    binary = Path(terraform).resolve(strict=True)
    before = fingerprint(binary)
    version = json.loads(command([str(binary), "version", "-json"]), object_pairs_hook=unique_object)
    metadata = command([go, "version", "-m", str(binary)])
    result = validate_observations(version, metadata, binary, expected_platform,
                                   platform.system(), platform.machine())
    digest = hashlib.sha256()
    with binary.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    require(fingerprint(binary) == before, "terraform_binary_changed_during_observation")
    return {"status": "PASS", **result, "terraform_binary_sha256": digest.hexdigest(),
            "terraform_binary_bytes": before[2], "go_metadata_from_same_binary": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-platform", choices=sorted(PLATFORMS), default="linux_arm64")
    args = parser.parse_args(argv)
    try:
        result = observe(args.expected_platform)
    except Exception as error:
        print(json.dumps({"status": "FAIL", "code": str(error) if isinstance(error, ToolchainError)
                          else "toolchain_observation_failed"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
