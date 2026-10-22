#!/usr/bin/env python3
"""Move DevFeed identity references while retaining application account UUIDs.

Requires psycopg and a private JSON map of old ZITADEL user IDs to new IDs.
The default is read-only. Apply only while the three sign-in APIs are stopped
through Fleet. This script does not change Kubernetes resources.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg

OLD_ISSUER = "https://auth.abhimanyu-saharan.com"
NEW_ISSUER = "https://auth.devfeed.tech"
OLD_ORG = "389593181982820082"
NEW_ORG = "395926894337328224"
APIS = ["devfeed-user-api", "devfeed-admin-api", "devfeed-partner-api"]


def owner_key(issuer, org, subject):
    return hashlib.sha256(
        json.dumps([issuer, org, subject], separators=(",", ":")).encode()
    ).hexdigest()


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--port", type=int, default=15439)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text())
    if not mapping or len(set(mapping.values())) != len(mapping):
        raise RuntimeError("Mapping must be nonempty and one-to-one")
    if args.apply:
        deployments = json.loads(
            subprocess.check_output(
                ["kubectl", "get", "deployment", *APIS, "-n", "devfeed", "-o", "json"]
            )
        )["items"]
        if len(deployments) != 3 or any(
            d["spec"]["replicas"] != 0 or d.get("status", {}).get("replicas", 0) != 0
            for d in deployments
        ):
            raise RuntimeError(
                "Stop all three sign-in APIs through Fleet before applying"
            )
    secret = json.loads(
        subprocess.check_output(
            [
                "kubectl",
                "get",
                "secret",
                "devfeed-database",
                "-n",
                "devfeed",
                "-o",
                "json",
            ]
        )
    )
    url = urlsplit(
        base64.b64decode(secret["data"]["DEVFEED_DATABASE_URL"])
        .decode()
        .replace("postgresql+psycopg://", "postgresql://")
    )
    with (
        psycopg.connect(
            host="127.0.0.1",
            port=args.port,
            user=unquote(url.username),
            password=unquote(url.password),
            dbname=url.path.lstrip("/"),
            connect_timeout=10,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '30s'")
        if args.apply:
            cursor.execute(
                "LOCK TABLE user_accounts, partner_memberships, admin_preferences IN ACCESS EXCLUSIVE MODE"
            )
        backup = {}
        for table in ["user_accounts", "partner_memberships", "admin_preferences"]:
            cursor.execute(f"SELECT to_jsonb(t) FROM {table} t")
            backup[table] = [row[0] for row in cursor.fetchall()]
        accounts = [
            row for row in backup["user_accounts"] if row["issuer"] == OLD_ISSUER
        ]
        partners = [
            row for row in backup["partner_memberships"] if row["issuer"] == OLD_ISSUER
        ]
        if not accounts:
            raise RuntimeError("No source accounts found; refuse an accidental rerun")
        if any(
            row["organization_id"] != OLD_ORG or row["subject"] not in mapping
            for row in accounts
        ):
            raise RuntimeError("Source account outside the verified mapping")
        if any(row["subject"] not in mapping for row in partners):
            raise RuntimeError("Partner membership outside the verified mapping")
        if any(
            row["issuer"] == NEW_ISSUER
            for row in backup["user_accounts"] + backup["partner_memberships"]
        ):
            raise RuntimeError(
                "Target database identities already exist; reconcile conflicts first"
            )
        preference_map = {
            owner_key(OLD_ISSUER, OLD_ORG, old): owner_key(NEW_ISSUER, NEW_ORG, new)
            for old, new in mapping.items()
        }
        preferences = [
            row
            for row in backup["admin_preferences"]
            if row["owner_key"] in preference_map
        ]
        if len(preferences) != len(backup["admin_preferences"]):
            raise RuntimeError(
                "Unmapped administrator preferences require investigation"
            )
        print(
            f"Plan: {len(accounts)} accounts, {len(partners)} partner memberships, {len(preferences)} preferences"
        )
        if not args.apply:
            connection.rollback()
            return
        private_json(args.mapping.parent / "database-before-cutover.json", backup)
        for row in accounts:
            cursor.execute(
                "UPDATE user_accounts SET issuer=%s, subject=%s, organization_id=%s "
                "WHERE id=%s AND issuer=%s AND subject=%s",
                (
                    NEW_ISSUER,
                    mapping[row["subject"]],
                    NEW_ORG,
                    row["id"],
                    OLD_ISSUER,
                    row["subject"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Unexpected user update count")
        for old, new in mapping.items():
            cursor.execute(
                "UPDATE partner_memberships SET issuer=%s, subject=%s WHERE issuer=%s AND subject=%s",
                (NEW_ISSUER, new, OLD_ISSUER, old),
            )
        for row in preferences:
            cursor.execute(
                "UPDATE admin_preferences SET owner_key=%s WHERE owner_key=%s",
                (preference_map[row["owner_key"]], row["owner_key"]),
            )
        # Verify every non-identity field, UUID and membership is unchanged.
        for table, rows_before in backup.items():
            cursor.execute(f"SELECT to_jsonb(t) FROM {table} t")
            actual = [row[0] for row in cursor.fetchall()]
            expected = json.loads(json.dumps(rows_before))
            for row in expected:
                if table == "user_accounts" and row["issuer"] == OLD_ISSUER:
                    row.update(
                        issuer=NEW_ISSUER,
                        subject=mapping[row["subject"]],
                        organization_id=NEW_ORG,
                    )
                elif table == "partner_memberships" and row["issuer"] == OLD_ISSUER:
                    row.update(issuer=NEW_ISSUER, subject=mapping[row["subject"]])
                elif (
                    table == "admin_preferences" and row["owner_key"] in preference_map
                ):
                    row["owner_key"] = preference_map[row["owner_key"]]
            if sorted(json.dumps(x, sort_keys=True) for x in actual) != sorted(
                json.dumps(x, sort_keys=True) for x in expected
            ):
                raise RuntimeError("Post-update invariant failed; rolling back")
        connection.commit()
        print(
            "Committed identity mappings; all non-identity fields and account UUIDs preserved"
        )


if __name__ == "__main__":
    main()
