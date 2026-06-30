set -euo pipefail
shopt -s nullglob

nvm_home="$HOME/.nvm"
nvm_dir="$nvm_home/nvm"
node_bin=""
expected_node_version="${EXPECTED_NODE_VERSION:-}"

default_alias=""
if [ -f "$nvm_dir/alias/default" ]; then
  default_alias="$(cat "$nvm_dir/alias/default")"
fi

candidates=()
if [ -n "$default_alias" ]; then
  candidates+=("$nvm_dir/versions/node/v${default_alias}"*/bin/node)
  candidates+=("$nvm_dir/versions/node/${default_alias}/bin/node")
fi
candidates+=("$nvm_dir"/versions/node/*/bin/node)

for candidate in "${candidates[@]}"; do
  if [ -x "$candidate" ]; then
    node_bin="$candidate"
    break
  fi
done

if [ -z "$node_bin" ] && command -v node >/dev/null 2>&1; then
  node_bin="$(command -v node)"
fi

if [ -z "$node_bin" ]; then
  if [ -n "$expected_node_version" ]; then
    echo "Node.js $expected_node_version was not found in the workspace image or under $nvm_dir/versions/node" >&2
  else
    echo "Node.js was not found in the workspace image or under $nvm_dir/versions/node" >&2
  fi
  exit 1
fi

node_version="$("$node_bin" --version)"
if [ -n "$expected_node_version" ] && [[ "$node_version" != "v${expected_node_version}"* ]]; then
  echo "Expected Node.js $expected_node_version but found $node_version at $node_bin" >&2
  exit 1
fi

if [ -s "$nvm_dir/nvm.sh" ]; then
  ln -sfn "$nvm_dir/nvm.sh" "$nvm_home/nvm.sh"
  if [ -s "$nvm_dir/bash_completion" ]; then
    ln -sfn "$nvm_dir/bash_completion" "$nvm_home/bash_completion"
  fi
fi

# Expose Node.js to shells and tools that do not source nvm.
node_dir="$(dirname "$node_bin")"
mkdir -p "$HOME/.local/bin"

link_command() {
  local target="$1"
  local name="$2"
  local local_link="$HOME/.local/bin/$name"

  if [ "$target" != "$local_link" ]; then
    ln -sfn "$target" "$local_link"
  fi

  # Coder SSH command sessions do not necessarily source user shell startup
  # files, so publish stable links on the default system PATH as well.
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo ln -sfn "$target" "/usr/local/bin/$name" || true
  fi
}

for bin in node npm npx corepack; do
  if [ -x "$node_dir/$bin" ]; then
    link_command "$node_dir/$bin" "$bin"
  elif command -v "$bin" >/dev/null 2>&1; then
    link_command "$(command -v "$bin")" "$bin"
  fi
done

export PATH="$HOME/.local/bin:$PATH"
"$HOME/.local/bin/node" --version
"$HOME/.local/bin/npm" --version

if [ -x "$HOME/.local/bin/corepack" ]; then
  "$HOME/.local/bin/corepack" enable --install-directory "$HOME/.local/bin" >/dev/null 2>&1 || true
fi

npm_prefix="$HOME/.local"
codex_bin="$HOME/.local/bin/codex"
if [ -L "$codex_bin" ] && [ "$(readlink "$codex_bin")" = "$codex_bin" ]; then
  rm -f "$codex_bin"
fi

image_codex_bin=""
if command -v codex >/dev/null 2>&1; then
  image_codex_bin="$(command -v codex)"
fi

if [ -n "$image_codex_bin" ] && [ "$image_codex_bin" != "$codex_bin" ] && [ -x "$image_codex_bin" ]; then
  link_command "$image_codex_bin" codex
elif ! NPM_CONFIG_PREFIX="$npm_prefix" NPM_CONFIG_UPDATE_NOTIFIER=false "$HOME/.local/bin/npm" list -g --depth=0 @openai/codex >/dev/null 2>&1 || [ ! -x "$codex_bin" ]; then
  NPM_CONFIG_PREFIX="$npm_prefix" NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_FUND=false NPM_CONFIG_AUDIT=false "$HOME/.local/bin/npm" install -g @openai/codex
  link_command "$codex_bin" codex
fi
"$codex_bin" --version
