"""Verify installed plugin versions against the image's exact requirements."""

import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re


def verify_plugins(requirements):
    checked = 0
    for number, line in enumerate(requirements.read_text().splitlines(), start=1):
        requirement = line.partition("#")[0].strip()
        if not requirement:
            continue
        pin = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)", requirement)
        if pin is None:
            raise ValueError(f"{requirements}:{number}: an exact package==version pin is required")
        package, expected = pin.groups()
        installed = version(package)
        if installed != expected:
            raise ValueError(f"{package}: expected {expected}, installed {installed}")
        checked += 1
    if not checked:
        raise ValueError(f"{requirements}: no plugin pins were found")
    print(f"Verified {checked} installed plugin versions against {requirements}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path)
    args = parser.parse_args()
    try:
        verify_plugins(args.requirements)
    except (PackageNotFoundError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
