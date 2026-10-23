#!/usr/bin/env python3
"""Check security floors in the generated pnpm 9 lockfile without extra tools.

This deliberately accepts the stable scalar/key forms emitted by pinned pnpm.
It is a structural security guard, not a general YAML parser. The actual build
also requires pnpm's full --frozen-lockfile validation before compilation.
"""

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent


def block(source, name):
    matches = list(re.finditer(rf"(?m)^{re.escape(name)}:\s*$", source))
    if len(matches) != 1:
        raise ValueError(f"expected one {name} block")
    start = matches[0].end()
    end = re.search(r"(?m)^\S", source[start:])
    return source[start:start + end.start()] if end else source[start:]


def scalar(value):
    value = value.strip()
    if value.startswith(("'", '"')):
        if len(value) < 2 or value[-1] != value[0]:
            raise ValueError("unsupported scalar quoting")
        value = value[1:-1]
    return value


def overrides(source):
    entries = {}
    for line in block(source, "overrides").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"  ('[^']+'|\"[^\"]+\"|[^:]+): (.+)", line)
        if not match:
            raise ValueError("unsupported override entry")
        key, value = map(scalar, match.groups())
        if key in entries:
            raise ValueError("duplicate override key")
        entries[key] = value
    if not entries:
        raise ValueError("empty overrides")
    return entries


def package_keys(source, section):
    keys = []
    for line in block(source, section).splitlines():
        if not line.startswith("  ") or line.startswith("   ") or not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"  ('[^']+'|\"[^\"]+\"|[^:]+):(?: \{\})?", line)
        if not match:
            raise ValueError(f"unsupported {section} package key")
        key = scalar(match[1])
        if key in keys:
            raise ValueError(f"duplicate {section} package key")
        keys.append(key)
    if not keys:
        raise ValueError(f"empty {section}")
    return keys


def version(value):
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("expected a stable semantic version")
    return tuple(map(int, value.split(".")))


def validate(workspace, lockfile, policy):
    errors = []
    try:
        floors = policy["minimumVersions"]
        if not isinstance(floors, dict) or not floors:
            raise ValueError("empty dependency policy")
        if not re.search(r"(?m)^lockfileVersion: ['\"]9\.0['\"]$", lockfile):
            raise ValueError("review a changed pnpm lockfile format")
        configured, locked = overrides(workspace), overrides(lockfile)
        sections = {name: package_keys(lockfile, name) for name in ("packages", "snapshots")}
        actual = {}
        for package, minimum in floors.items():
            floor = version(minimum)
            selected = [key for key in configured if key == package or key.startswith(package + "@")]
            if len(selected) != 1:
                raise ValueError(f"{package}: expected one explicit override")
            key = selected[0]
            chosen = configured[key]
            caret = chosen.startswith("^")
            if caret:
                chosen = chosen[1:]
            chosen_version = version(chosen)
            if chosen_version < floor or chosen_version[0] != floor[0]:
                errors.append(f"{package}: override is below the reviewed floor or changes major")
            if locked.get(key) != configured[key]:
                errors.append(f"{package}: workspace and lock overrides differ")
            actual[package] = chosen
            for name, keys in sections.items():
                resolved = [key[len(package) + 1:].split("(", 1)[0]
                            for key in keys if key.startswith(package + "@")]
                if not resolved:
                    errors.append(f"{package}: missing {name} resolutions")
                for resolved_version in resolved:
                    current = version(resolved_version)
                    if current < floor or current[0] != floor[0]:
                        errors.append(f"{package}: vulnerable or unreviewed {name} resolution")
                    if (current < chosen_version if caret else current != chosen_version):
                        errors.append(f"{package}: override and {name} resolution differ")
        for cohort in policy["versionCohorts"]:
            if len(cohort) < 2 or any(package not in actual for package in cohort):
                raise ValueError("invalid dependency version cohort")
            if len({actual[package] for package in cohort}) != 1:
                errors.append("version cohort must move together")
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT / "pnpm-workspace.yaml")
    parser.add_argument("--lockfile", type=Path, default=ROOT / "pnpm-lock.yaml")
    parser.add_argument("--policy", type=Path, default=ROOT / "dependency-policy.json")
    args = parser.parse_args(argv)
    errors = validate(args.workspace.read_text(), args.lockfile.read_text(), json.loads(args.policy.read_text()))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Patched dependency floors and workspace/lock version cohorts match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
