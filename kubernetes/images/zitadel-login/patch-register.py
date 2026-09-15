from pathlib import Path

path = Path('/src/apps/login/src/lib/server/register.ts')
source = path.read_text()
start = '  const session = await createSessionForIdpAndUpdateCookie({'
end = '    lifetime: loginSettings?.externalLoginCheckLifetime,\n  });'
assert source.count(start) == 1, 'Upstream IDP session call changed; review patch'
assert source.count(end) == 1, 'Upstream IDP session options changed; review patch'
source = source.replace('"use server";', '"use server";\n\nimport { retryNotFound } from "./retry-not-found";', 1)
assert 'import { retryNotFound }' in source
source = source.replace(start, '  const session = await retryNotFound(() => createSessionForIdpAndUpdateCookie({', 1)
source = source.replace(end, '    lifetime: loginSettings?.externalLoginCheckLifetime,\n  }));', 1)
path.write_text(source)

# Next 16.3 checks every included test fixture during the production build.
# Keep strict runtime checking while Vitest separately runs regression tests.
import json
config_path = Path('/src/apps/login/tsconfig.json')
config = json.loads(config_path.read_text())
config['exclude'].extend(['**/*.test.ts', '**/*.test.tsx', 'tests', 'test-setup.ts'])
config_path.write_text(json.dumps(config, indent=2) + '\n')
