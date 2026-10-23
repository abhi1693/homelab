"""Linux, stdlib-only read-only receipt verification under an explicit NAS policy.

The caller verifies live Pod/PVC/PV bindings and supplies their exact mount and
expected first-init metadata. This utility does not query Kubernetes, rehash or
read the archive, inspect its manifest/keys, open SQLite, chmod or restore data.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid

POINT = re.compile(r"point-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


class VerificationError(Exception):
    """Only a static error code, never untrusted paths or receipt values."""


def require(ok, code):
    if not ok:
        raise VerificationError(code)


def strict_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate_json_key")
            out[key] = value
        return out
    def constant(_value):
        raise VerificationError("nonfinite_json_value")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def validate_policy(policy):
    require(policy.get("schema_version") == 1 and policy.get("receipt_format") == 1,
            "unsupported_policy_format")
    require(policy.get("owner_only") is False and policy.get("encryption_claimed") is False,
            "unsupported_privacy_claim")
    require(policy.get("claim_root_mode") == "record-separately", "invalid_claim_root_policy")
    require(isinstance(policy.get("policy_id"), str) and NAME.fullmatch(policy["policy_id"]),
            "invalid_policy_identity")
    owner = policy.get("mapped_owner", {})
    require(all(type(owner.get(key)) is int and owner[key] >= 0 for key in ["uid", "gid"]),
            "invalid_mapped_owner")
    dirs = {int(value, 8) for value in policy.get("protected_directory_modes", [])}
    files = {int(value, 8) for value in policy.get("protected_file_modes", [])}
    require(dirs == {0o700, 0o770} and files == {0o600, 0o660}, "unsupported_permission_policy")
    require(type(policy.get("max_receipt_bytes")) is int and 0 < policy["max_receipt_bytes"] <= 8192,
            "invalid_receipt_bound")
    require(isinstance(policy.get("owners"), list) and policy["owners"] and
            all(isinstance(x, str) and NAME.fullmatch(x) for x in policy["owners"]),
            "invalid_owner_allowlist")
    return dirs, files


def metadata(st):
    return {"mode": f"{stat.S_IMODE(st.st_mode):04o}", "uid": st.st_uid,
            "gid": st.st_gid, "bytes": st.st_size, "links": st.st_nlink}


def check_stat(st, kind, policy, protected=True):
    require((stat.S_ISDIR if kind == "directory" else stat.S_ISREG)(st.st_mode), "wrong_object_type")
    require((st.st_uid, st.st_gid) == (policy["mapped_owner"]["uid"], policy["mapped_owner"]["gid"]),
            "mapped_owner_group_mismatch")
    if protected:
        modes = policy["protected_directory_modes" if kind == "directory" else "protected_file_modes"]
        require(stat.S_IMODE(st.st_mode) in {int(x, 8) for x in modes}, "unsafe_protected_permissions")
    if kind == "file":
        require(st.st_nlink == 1, "linked_protected_file")


def fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def open_mount(path):
    require(isinstance(path, str) and path.startswith("/") and
            str(PurePosixPath(path)) == path and ".." not in PurePosixPath(path).parts,
            "invalid_mount_path")
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in PurePosixPath(path).parts[1:]:
            new = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd
    except Exception:
        os.close(fd)
        raise


def expected_metadata(request, policy):
    require(request.get("owner") in policy["owners"], "unexpected_owner")
    require(isinstance(request.get("point"), str) and POINT.fullmatch(request["point"]), "invalid_point")
    for key in ["pod_uid", "expected_source_pvc_uid"]:
        require(isinstance(request.get(key), str) and str(uuid.UUID(request[key])) == request[key],
                "invalid_expected_identity")
    for key in ["source_pvc", "cohort"]:
        require(isinstance(request.get(key), str) and NAME.fullmatch(request[key]), "invalid_expected_identity")
    require(request.get("restored_verified") is True, "expected_restore_verification_required")
    term = request.get("termination", {})
    require(term.get("status") == "verified" and term.get("point") == request["point"],
            "unverified_termination")
    require(isinstance(term.get("archive_sha256"), str) and SHA.fullmatch(term["archive_sha256"]),
            "invalid_expected_archive_hash")
    require(all(type(term.get(key)) is int and term[key] > 0 for key in ["archive_bytes", "file_count"]),
            "invalid_expected_archive_counts")
    expected = {key: request[key] for key in ["owner", "point", "pod_uid", "cohort", "source_pvc", "expected_source_pvc_uid", "restored_verified"]}
    expected.update({key: term[key] for key in ["archive_sha256", "archive_bytes", "file_count"]})
    expected["format"] = policy["receipt_format"]
    return expected


def verify_receipt(request, policy):
    validate_policy(policy)
    expected = expected_metadata(request, policy)
    for key in ["uid", "gid"]:
        require(type(request.get(key)) is int and request[key] >= 0, "invalid_reader_identity")
    handles = []
    def hold(fd):
        handles.append(fd)
        return fd
    try:
        root = hold(open_mount(request["mount"]))
        root_st = os.fstat(root)
        check_stat(root_st, "directory", policy, protected=False)
        # Limit directory/file reads to the same unprivileged identity as the init.
        if (os.geteuid(), os.getegid()) != (request["uid"], request["gid"]):
            require(os.geteuid() == 0, "reader_identity_mismatch")
            os.setgroups([request["gid"]])
            os.setgid(request["gid"])
            os.setuid(request["uid"])
        require(set(os.getgroups()) <= {request["gid"]}, "unexpected_reader_supplementary_groups")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        owner = hold(os.open(request["owner"], flags, dir_fd=root))
        point = hold(os.open(request["point"], flags, dir_fd=owner))
        owner_st, point_st = os.fstat(owner), os.fstat(point)
        check_stat(owner_st, "directory", policy)
        check_stat(point_st, "directory", policy)
        require(set(os.listdir(point)) == {"receipt.json", "state.tar"}, "unexpected_point_contents")
        receipt = hold(os.open("receipt.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=point))
        receipt_st = os.fstat(receipt)
        check_stat(receipt_st, "file", policy)
        require(0 < receipt_st.st_size <= policy["max_receipt_bytes"], "receipt_exceeds_bound")
        body = os.read(receipt, policy["max_receipt_bytes"] + 1)
        require(len(body) == receipt_st.st_size and len(body) <= policy["max_receipt_bytes"],
                "receipt_changed_or_exceeds_bound")
        raw = strict_json(body)
        require(isinstance(raw, dict) and all(type(raw.get(key)) is type(value) and raw.get(key) == value
                for key, value in expected.items()), "receipt_identity_or_metadata_mismatch")
        # O_PATH permits metadata only; no archive body is opened for reading.
        archive = hold(os.open("state.tar", os.O_PATH | os.O_NOFOLLOW, dir_fd=point))
        archive_st = os.fstat(archive)
        check_stat(archive_st, "file", policy)
        require(archive_st.st_size == expected["archive_bytes"], "archive_size_mismatch")
        for descriptor, name, parent, initial in [(receipt, "receipt.json", point, receipt_st),
                (archive, "state.tar", point, archive_st), (point, request["point"], owner, point_st),
                (owner, request["owner"], root, owner_st)]:
            require(fingerprint(os.fstat(descriptor)) == fingerprint(initial) and
                    fingerprint(os.stat(name, dir_fd=parent, follow_symlinks=False)) == fingerprint(initial),
                    "object_replaced_or_changed")
        # The root fd was selected with no-follow on every component before dropping
        # privileges. Do not traverse protected kubelet parents as the init UID.
        require(fingerprint(os.fstat(root)) == fingerprint(root_st), "mount_metadata_changed")
        strict = all(stat.S_IMODE(x.st_mode) == 0o700 for x in [owner_st, point_st]) and all(
            stat.S_IMODE(x.st_mode) == 0o600 for x in [receipt_st, archive_st])
        return {"status": "PASS", "policy_id": policy["policy_id"], "owner_only": False,
                "encryption_claimed": False, "stricter_protected_modes_observed": strict,
                "privacy_policy_satisfied": True, "identity_matches": True,
                "termination_matches_stored_receipt": True, "archive_size_matches": True,
                "restored_verified": True, "archive_sha256": expected["archive_sha256"],
                "archive_bytes": expected["archive_bytes"], "file_count": expected["file_count"],
                "directories": {"claim_root": metadata(root_st), "owner": metadata(owner_st), "point": metadata(point_st)},
                "files": {"receipt": metadata(receipt_st), "archive": metadata(archive_st)},
                "claim_root_mode_recorded_separately": True, "archive_body_read": False,
                "archive_hash_recomputed": False, "per_file_manifest_read": False,
                "key_data_read": False, "database_opened": False}
    finally:
        for fd in reversed(handles):
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--policy", type=Path)
    group.add_argument("--policy-json")
    args = parser.parse_args()
    try:
        policy = strict_json(args.policy_json) if args.policy_json else strict_json(
            (args.policy or Path(__file__).with_name("backup-storage-policy.json")).read_text())
        result = verify_receipt(strict_json(args.request_json), policy)
    except Exception as error:
        result = {"status": "FAIL", "error_type": type(error).__name__,
                  "code": str(error) if isinstance(error, VerificationError) else "receipt_metadata_verification_failed",
                  "archive_body_read": False, "key_data_read": False, "database_opened": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
