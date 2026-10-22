#!/usr/bin/env python3
"""Reconcile only the DevFeed instance's generic SMTP provider."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def reconcile(api, config, token, password):
    """Check the instance boundary before making any configuration changes."""
    instance = api('GET', '/admin/v1/instances/me', None)['instance']
    if instance['id'] != config['instanceId']:
        raise RuntimeError('Instance mismatch; refusing SMTP changes')
    desired = config['smtp'].copy()
    prefix = 'devfeed-gitops:'
    fingerprint = hmac.new(token.encode(), json.dumps(
        [desired, password], sort_keys=True).encode(), hashlib.sha256).hexdigest()
    desired['description'] = prefix + fingerprint
    providers = api('POST', '/admin/v1/email/_search', {}).get('result', [])
    matches = [p for p in providers if p.get('description', '').startswith(prefix)]
    if len(matches) > 1:
        raise RuntimeError('Multiple managed SMTP providers; refusing ambiguous update')
    current = matches[0] if matches else None
    if not password:
        # Never create or activate a provider with a missing authentication token.
        print('SMTP pending: populate zitadel-devfeed-smtp/password through SOPS GitOps')
        return
    # The sender uses devfeed.tech while the issuer uses auth.devfeed.tech.
    policy = api('GET', '/admin/v1/policies/domain', None)['policy']
    if policy.get('smtpSenderAddressMatchesInstanceDomain', False):
        api('PUT', '/admin/v1/policies/domain', {
            'userLoginMustBeDomain': policy.get('userLoginMustBeDomain', False),
            'validateOrgDomains': policy.get('validateOrgDomains', False),
            'smtpSenderAddressMatchesInstanceDomain': False,
        })
    body = dict(desired, plain={'password': password})
    if current is None:
        provider_id = api('POST', '/admin/v1/email/smtp', body)['id']
    else:
        provider_id = current['id']
        fields = config['smtp']
        settings_match = all(current.get('smtp', {}).get(k, '') == v
                             for k, v in fields.items())
        if current.get('description') != desired['description'] or not settings_match:
            api('PUT', '/admin/v1/email/smtp/' + provider_id, body)
    if current is None or current.get('state') != 'EMAIL_PROVIDER_ACTIVE':
        api('POST', '/admin/v1/email/' + provider_id + '/_activate', {})
    print('DevFeed SMTP provider reconciled')


def main():
    config = json.loads(Path(os.getenv('SMTP_CONFIG', '/config/settings.json')).read_text())
    token = Path(os.getenv('API_TOKEN_FILE', '/credentials/api/token')).read_text().strip()
    password = Path(os.getenv('SMTP_PASSWORD_FILE', '/credentials/smtp/password')).read_text().strip()
    if not token:
        raise RuntimeError('Missing instance automation token')

    def api(method, path, body):
        request = urllib.request.Request(
            os.getenv('ZITADEL_API_URL', 'http://zitadel:8080') + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token,
                     'Content-Type': 'application/json',
                     'Host': 'auth.devfeed.tech',
                     'X-Zitadel-Public-Host': 'auth.devfeed.tech'}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Never log request bodies, headers or server responses containing secrets.
            raise RuntimeError(f'ZITADEL API returned HTTP {error.code} for {path}') from None

    reconcile(api, config, token, password)


if __name__ == '__main__':
    main()
