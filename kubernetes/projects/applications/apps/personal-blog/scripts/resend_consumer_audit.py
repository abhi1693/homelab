"""Trusted-control-plane-only bounded audit; never exports credential material.

stdin initial: {"mode":"initial"}; retirement: comparison_literal=old encrypted
journal value and expected_current_literal=new journal value, via private stdin.
Only namespace/name/type/key-name metadata is projected across all Secrets.
Only exact selected candidate Secrets are then read privately; only candidate
field values are base64-decoded. No provider or Kubernetes mutation exists.
"""
import base64
from collections import Counter
import json
import re
import resource
import subprocess
import sys
import time

TARGET = ('personal-blog', 'personal-blog', 'RESEND_API_KEY_FULL')
EXCLUDED_TYPES = {'kubernetes.io/tls', 'kubernetes.io/service-account-token',
    'kubernetes.io/dockerconfigjson', 'kubernetes.io/dockercfg',
    'bootstrap.kubernetes.io/token', 'kubernetes.io/ssh-auth', 'helm.sh/release.v1'}
ALLOWED_TYPES = {'Opaque', '', '<no value>', 'kubernetes.io/basic-auth'}
PROVIDER = re.compile(r'resend|smtp|mail|email|sendgrid|postmark|mandrill|(?:^|[._-])ses(?:[._-]|$)', re.I)
BLOB = re.compile(r'(?:^|[._-])(?:env|environment|envvars|config|configuration|settings|appsettings)(?:[._-]|$)|^(?:application|values)(?:\.(?:json|ya?ml|toml|ini|properties|conf))?$', re.I)
CRYPTO_FIELD = re.compile(r'^(?:tls\.(?:crt|key)|ca\.(?:crt|key)|ssh-privatekey|id_rsa|id_ed25519|\.dockerconfigjson|\.dockercfg)$|\.(?:crt|pem|der|p12|pfx)$', re.I)
NAME = re.compile(r'[a-z0-9][a-z0-9.-]{0,252}\Z')
KEY = re.compile(r'[-._a-zA-Z0-9]+\Z')
KUBECTL = ['sudo', '-n', '/usr/local/bin/k3s', 'kubectl',
    '--kubeconfig=/etc/rancher/k3s/k3s.yaml', '--server=https://127.0.0.1:6443',
    '--request-timeout=10s']
TEMPLATE = r'{{range .items}}{{.metadata.namespace}}{{"\t"}}{{.metadata.name}}{{"\t"}}{{.metadata.uid}}{{"\t"}}{{.metadata.resourceVersion}}{{"\t"}}{{.type}}{{"\t"}}{{range $key, $_ := .data}}{{$key}}{{","}}{{end}}{{"\n"}}{{end}}'


class AuditError(Exception):
    pass


def require(good, code):
    if not good:
        raise AuditError(code)


def candidate_keys(record):
    if record['type'] in EXCLUDED_TYPES or record['type'] not in ALLOWED_TYPES:
        return []
    named = PROVIDER.search(record['name']) is not None
    return [key for key in record['keys'] if not CRYPTO_FIELD.search(key)
            and (named or PROVIDER.search(key) or BLOB.search(key))]


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    started = time.monotonic()
    counts = Counter()
    matches = []
    report = {'complete': False, 'error_flags': {}, 'counts': {}, 'matches': matches,
              'target_stable': False, 'candidate_snapshot_stable': False}

    def command(args, bound):
        remaining = 120 - (time.monotonic() - started)
        require(remaining > 0, 'audit_time_bound')
        try:
            result = subprocess.run(KUBECTL + args, capture_output=True,
                timeout=min(12, remaining), check=False)
        except Exception:
            raise AuditError('api_read_failed') from None
        require(result.returncode == 0, 'api_read_denied_or_failed')
        require(len(result.stdout) <= bound, 'api_payload_bound')
        return result.stdout

    def get_secret(namespace, name):
        require(NAME.fullmatch(namespace) and NAME.fullmatch(name), 'invalid_secret_metadata')
        result = json.loads(command(['get', '--raw',
            '/api/v1/namespaces/' + namespace + '/secrets/' + name], 2097152))
        require(result.get('kind') == 'Secret' and result['metadata']['namespace'] == namespace
                and result['metadata']['name'] == name, 'secret_identity_mismatch')
        return result

    def discover():
        raw = command(['get', 'secrets', '--all-namespaces', '-o',
                       'go-template=' + TEMPLATE], 1048576)
        records = {}
        for line in raw.decode().splitlines():
            parts = line.split('\t')
            require(len(parts) == 6, 'metadata_projection_invalid')
            namespace, name, uid, rv, kind, keys = parts
            require(NAME.fullmatch(namespace) and NAME.fullmatch(name), 'invalid_secret_metadata')
            key_list = sorted(key for key in keys.split(',') if key)
            require(len(key_list) <= 256 and all(KEY.fullmatch(key) for key in key_list), 'metadata_key_bound')
            identity = (namespace, name)
            require(identity not in records, 'duplicate_secret_metadata')
            records[identity] = {'namespace': namespace, 'name': name, 'uid': uid,
                'rv': rv, 'type': kind, 'keys': key_list}
        require(0 < len(records) <= 1500, 'metadata_record_bound')
        return records

    def decoded(value):
        require(isinstance(value, str) and len(value) <= 1398104, 'candidate_field_bound')
        try:
            out = base64.b64decode(value, validate=True)
        except Exception:
            raise AuditError('candidate_base64_invalid') from None
        counts['decoded_fields'] += 1
        counts['decoded_bytes_private'] += len(out)
        require(len(out) <= 1048576 and counts['decoded_bytes_private'] <= 16777216, 'candidate_decode_bound')
        return out

    def stable_projection(records):
        return {identity: (record['uid'], record['type'], tuple(record['keys']),
                          record['rv'] if candidate_keys(record) else None)
                for identity, record in records.items()}

    try:
        request = sys.stdin.buffer.read(16385)
        require(len(request) <= 16384, 'request_bound')
        request = json.loads(request)
        require(request.get('mode') in ['initial', 'retirement'], 'invalid_audit_mode')
        initial = get_secret(*TARGET[:2])
        require(initial.get('type', 'Opaque') in ALLOWED_TYPES and TARGET[2] in initial.get('data', {}),
                'unexpected_target_secret')
        current_target = decoded(initial['data'][TARGET[2]])
        require(0 < len(current_target) <= 4096, 'target_field_bound')
        if request['mode'] == 'initial':
            literal = current_target
        else:
            require(isinstance(request.get('comparison_literal'), str)
                and isinstance(request.get('expected_current_literal'), str), 'retirement_literals_required')
            literal = request['comparison_literal'].encode()
            require(0 < len(literal) <= 4096 and current_target == request['expected_current_literal'].encode()
                    and literal != current_target, 'retirement_target_mismatch')
        before = discover()
        require(TARGET[:2] in before and before[TARGET[:2]]['uid'] == initial['metadata']['uid']
                and before[TARGET[:2]]['rv'] == initial['metadata']['resourceVersion'], 'target_snapshot_mismatch')
        counts['metadata_secrets'] = len(before)
        counts['metadata_fields'] = sum(len(record['keys']) for record in before.values())
        counts['excluded_type_secrets'] = sum(record['type'] not in ALLOWED_TYPES or record['type'] in EXCLUDED_TYPES
                                              for record in before.values())
        candidates = [(identity, record, candidate_keys(record)) for identity, record in sorted(before.items())
                      if candidate_keys(record)]
        counts['candidate_secrets'] = len(candidates)
        counts['candidate_fields'] = sum(len(keys) for _, _, keys in candidates)
        require(counts['candidate_secrets'] <= 200 and counts['candidate_fields'] <= 800, 'candidate_inventory_bound')
        for (namespace, name), record, keys in candidates:
            raw = initial if (namespace, name) == TARGET[:2] else get_secret(namespace, name)
            counts['candidate_secrets_read'] += 1
            require(raw['metadata']['uid'] == record['uid'] and raw['metadata']['resourceVersion'] == record['rv']
                    and raw.get('type', 'Opaque') == record['type']
                    and sorted(raw.get('data', {})) == record['keys'], 'candidate_snapshot_changed')
            for key in keys:
                value = decoded(raw['data'][key])
                if value == literal or literal in value:
                    matches.append({'namespace': namespace, 'secret': name, 'key': key})
        after = discover()
        report['candidate_snapshot_stable'] = stable_projection(before) == stable_projection(after)
        require(report['candidate_snapshot_stable'], 'candidate_snapshot_changed')
        last = get_secret(*TARGET[:2])
        report['target_stable'] = (last['metadata']['uid'] == initial['metadata']['uid']
            and last['metadata']['resourceVersion'] == initial['metadata']['resourceVersion']
            and decoded(last['data'][TARGET[2]]) == current_target)
        require(report['target_stable'], 'target_changed_during_audit')
        report['complete'] = True
    except Exception as error:
        report['error_flags'][str(error) if isinstance(error, AuditError) else 'audit_failed'] = True
    counts.pop('decoded_bytes_private', None)
    counts['matching_fields'] = len(matches)
    counts['other_matching_fields'] = sum((item['namespace'], item['secret'], item['key']) != TARGET for item in matches)
    report['counts'] = dict(counts)
    report['other_consumers_present'] = counts['other_matching_fields'] > 0
    print(json.dumps(report, sort_keys=True))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
