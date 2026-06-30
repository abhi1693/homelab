set -euo pipefail

setup_log() {
  printf '[workspace setup %s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"
}

: "${PYCHARM_VERSION:?PYCHARM_VERSION is required}"
: "${PYCHARM_BUILD:?PYCHARM_BUILD is required}"
: "${PYCHARM_LINUX_ARM64_URL:?PYCHARM_LINUX_ARM64_URL is required}"
: "${PYCHARM_LINUX_ARM64_SHA:?PYCHARM_LINUX_ARM64_SHA is required}"
: "${PYCHARM_HEAP_MB:?PYCHARM_HEAP_MB is required}"
: "${PYCHARM_CONFIG_DIR:?PYCHARM_CONFIG_DIR is required}"
: "${PYCHARM_PROJECT_DIR:?PYCHARM_PROJECT_DIR is required}"

mkdir -p "$HOME/work" "$HOME/.local/bin" "$HOME/.local/share/JetBrains/Toolbox/apps" "$HOME/.cache/JetBrains/RemoteDev/dist" "$HOME/JetBrains"

pycharm_dir="$HOME/.local/share/JetBrains/Toolbox/apps/pycharm"
legacy_pycharm_dir="$HOME/JetBrains/pycharm-professional-${PYCHARM_BUILD}-aarch64"
expected_pycharm_build="PY-${PYCHARM_BUILD}"
pycharm_config_dir="$PYCHARM_CONFIG_DIR"
pycharm_project_dir="$PYCHARM_PROJECT_DIR"
pycharm_heap_mb="$PYCHARM_HEAP_MB"
repo_url="$(printf '%s' "${WORKSPACE_REPO_URL_B64:-}" | base64 -d 2>/dev/null || true)"

configure_pycharm_runtime() {
  config_dir="$HOME/.config/JetBrains/$pycharm_config_dir"
  options_dir="$config_dir/options"
  settings_sync_options_dir="$config_dir/settingsSync/options"
  mkdir -p "$options_dir" "$settings_sync_options_dir"

  PYCHARM_CONFIG_DIR_PATH="$config_dir" PYCHARM_HEAP_MB="$pycharm_heap_mb" python3 - <<'PY'
import os
from pathlib import Path
from xml.etree import ElementTree as ET

config_dir = Path(os.environ["PYCHARM_CONFIG_DIR_PATH"])
heap_mb = int(os.environ["PYCHARM_HEAP_MB"])
heap_line = f"-Xmx{heap_mb}m"

vmoptions_path = config_dir / "pycharm64.vmoptions"
lines = vmoptions_path.read_text(encoding="utf-8").splitlines() if vmoptions_path.exists() else []
updated = []
heap_written = False
for line in lines:
    if line.startswith("-Xmx"):
        if not heap_written:
            updated.append(heap_line)
            heap_written = True
        continue
    updated.append(line)
if not heap_written:
    updated.insert(0, heap_line)
vmoptions_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")

def parse_or_new(path):
    if path.exists() and path.stat().st_size:
        try:
            return ET.parse(path)
        except ET.ParseError:
            pass
    return ET.ElementTree(ET.Element("application"))

def get_component(root, name):
    for component in root.findall("component"):
        if component.get("name") == name:
            return component
    return ET.SubElement(root, "component", {"name": name})

def get_option(parent, name):
    for option in parent.findall("option"):
        if option.get("name") == name:
            return option
    return ET.SubElement(parent, "option", {"name": name})

def set_option(parent, name, value):
    option = get_option(parent, name)
    option.set("value", value)
    return option

def write_tree(tree, path):
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=False)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n")

def allow_python_shared_indexes(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = parse_or_new(path)
    root = tree.getroot()
    component = get_component(root, "download-consent")
    consent_items = get_option(component, "consentItems")
    for item in consent_items.findall("item"):
        if item.get("kind") == "python" and item.get("url") == "https://index-cdn.jetbrains.com/v2/py_pkg":
            item.set("download", "ALLOWED")
            write_tree(tree, path)
            return
    ET.SubElement(consent_items, "item", {
        "download": "ALLOWED",
        "kind": "python",
        "url": "https://index-cdn.jetbrains.com/v2/py_pkg",
    })
    write_tree(tree, path)

def enable_settings_sync(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = parse_or_new(path)
    root = tree.getroot()
    component = get_component(root, "SettingsSyncSettings")
    set_option(component, "migrationFromOldStorageChecked", "true")
    set_option(component, "syncEnabled", "true")
    write_tree(tree, path)

def configure_settings_sync_account(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = parse_or_new(path)
    root = tree.getroot()
    component = get_component(root, "SettingsSyncLocalSettings")
    set_option(component, "providerCode", "jba")
    set_option(component, "remoteDataRemovalState", "OK")
    set_option(component, "userId", "jba")
    write_tree(tree, path)

for shared_indexes_path in (
    config_dir / "options" / "shared-indexes.xml",
    config_dir / "settingsSync" / "options" / "shared-indexes.xml",
):
    allow_python_shared_indexes(shared_indexes_path)

for settings_sync_path in (
    config_dir / "options" / "settingsSync.xml",
    config_dir / "settingsSync" / "options" / "settingsSync.xml",
):
    enable_settings_sync(settings_sync_path)

configure_settings_sync_account(config_dir / "options" / "settingsSyncLocal.xml")
PY

  setup_log "Configured PyCharm runtime defaults with ${pycharm_heap_mb} MiB heap and account sync enabled"
}

configure_pycharm_default_project() {
  project_dir="$1"
  if [ -n "$repo_url" ]; then
    setup_log "Waiting for repository at $project_dir before configuring PyCharm"
    for _ in $(seq 1 120); do
      if [ -d "$project_dir/.git" ]; then
        break
      fi
      sleep 1
    done

    if [ ! -d "$project_dir/.git" ]; then
      setup_log "Repository was not ready at $project_dir; PyCharm will default to $HOME"
      project_dir="$HOME"
    fi
  fi

  mkdir -p "$HOME/.config/JetBrains/$pycharm_config_dir/options"

  project_name="$(basename "$project_dir")"
  if [ "$project_dir" != "$HOME" ] && [ -d "$project_dir/.git" ]; then
    remote_url="$(git -C "$project_dir" remote get-url origin 2>/dev/null || true)"
    remote_project_name="$(basename "$(printf '%s' "$remote_url" | sed 's#/*$##; s#\.git$##')")"
    if [ -n "$remote_project_name" ]; then
      project_name="$remote_project_name"
    fi
  fi

  PYCHARM_PROJECT_DIR="$project_dir" PYCHARM_PROJECT_NAME="$project_name" PYCHARM_CONFIG_DIR="$pycharm_config_dir" PYCHARM_BUILD="$PYCHARM_BUILD" python3 - <<'PY'
import os
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

home = Path(os.environ["HOME"]).resolve()
project = Path(os.environ["PYCHARM_PROJECT_DIR"]).resolve()
project_name = os.environ.get("PYCHARM_PROJECT_NAME") or project.name
options_dir = home / ".config" / "JetBrains" / os.environ["PYCHARM_CONFIG_DIR"] / "options"
options_dir.mkdir(parents=True, exist_ok=True)

def macro_path(path):
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "$USER_HOME$" if str(relative) == "." else "$USER_HOME$/" + str(relative)

def parse_or_new(path):
    if path.exists() and path.stat().st_size:
        try:
            return ET.parse(path)
        except ET.ParseError:
            pass
    return ET.ElementTree(ET.Element("application"))

def get_component(root, name):
    for component in root.findall("component"):
        if component.get("name") == name:
            return component
    return ET.SubElement(root, "component", {"name": name})

def get_option(parent, name):
    for option in parent.findall("option"):
        if option.get("name") == name:
            return option
    return ET.SubElement(parent, "option", {"name": name})

def get_child(parent, tag):
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    return child

def write_tree(tree, path):
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=False)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n")

project_key = macro_path(project)
now_ms = str(int(time.time() * 1000))
workspace_id = uuid.uuid5(uuid.NAMESPACE_URL, str(project)).hex[:27]

recent_path = options_dir / "recentProjects.xml"
recent_tree = parse_or_new(recent_path)
recent_root = recent_tree.getroot()
recent = get_component(recent_root, "RecentProjectsManager")
additional_info = get_option(recent, "additionalInfo")
projects_map = get_child(additional_info, "map")

for meta in recent_root.iter("RecentProjectMetaInfo"):
    if meta.get("opened") == "true":
        meta.set("opened", "false")

for entry in list(projects_map.findall("entry")):
    if entry.get("key") == project_key:
        projects_map.remove(entry)

entry = ET.SubElement(projects_map, "entry", {"key": project_key})
value = ET.SubElement(entry, "value")
meta = ET.SubElement(value, "RecentProjectMetaInfo", {
    "frameTitle": project_name,
    "opened": "true",
    "projectWorkspaceId": workspace_id,
})
ET.SubElement(meta, "option", {"name": "activationTimestamp", "value": now_ms})
ET.SubElement(meta, "option", {"name": "binFolder", "value": "$APPLICATION_HOME_DIR$/bin"})
ET.SubElement(meta, "option", {"name": "build", "value": "PY-" + os.environ["PYCHARM_BUILD"]})
ET.SubElement(meta, "option", {"name": "productionCode", "value": "PY"})
ET.SubElement(meta, "option", {"name": "projectOpenTimestamp", "value": now_ms})

for option in list(recent.findall("option")):
    if option.get("name") == "lastOpenedProject":
        recent.remove(option)
ET.SubElement(recent, "option", {"name": "lastOpenedProject", "value": project_key})
write_tree(recent_tree, recent_path)

trusted_path = options_dir / "trusted-paths.xml"
trusted_tree = parse_or_new(trusted_path)
trusted_root = trusted_tree.getroot()
trusted = get_component(trusted_root, "Trusted.Paths")
trusted_option = get_option(trusted, "TRUSTED_PROJECT_PATHS")
trusted_map = get_child(trusted_option, "map")
for entry in list(trusted_map.findall("entry")):
    if entry.get("key") == project_key:
        trusted_map.remove(entry)
ET.SubElement(trusted_map, "entry", {"key": project_key, "value": "true"})
write_tree(trusted_tree, trusted_path)

general_path = options_dir / "ide.general.local.xml"
general_tree = parse_or_new(general_path)
general_root = general_tree.getroot()
general = get_component(general_root, "GeneralLocalSettings")
for option in list(general.findall("option")):
    if option.get("name") == "defaultProjectDirectory":
        general.remove(option)
ET.SubElement(general, "option", {"name": "defaultProjectDirectory", "value": project_key})
write_tree(general_tree, general_path)
PY

  setup_log "Configured PyCharm to open $project_dir"
}

setup_log "Checking PyCharm Professional ${PYCHARM_VERSION} backend"
pycharm_installed_build="$(cat "$pycharm_dir/build.txt" 2>/dev/null || true)"
legacy_pycharm_build="$(cat "$legacy_pycharm_dir/build.txt" 2>/dev/null || true)"

if [ "$pycharm_installed_build" != "$expected_pycharm_build" ] && [ "$legacy_pycharm_build" = "$expected_pycharm_build" ]; then
  setup_log "Moving existing PyCharm backend into Toolbox-managed path"
  rm -rf "$pycharm_dir"
  mv "$legacy_pycharm_dir" "$pycharm_dir"
  pycharm_installed_build="$legacy_pycharm_build"
fi

if [ ! -x "$pycharm_dir/bin/remote-dev-server.sh" ] || [ "$pycharm_installed_build" != "$expected_pycharm_build" ]; then
  setup_log "PyCharm backend not found at $pycharm_dir with build $expected_pycharm_build; installing"
  tmp_dir="$(mktemp -d "$HOME/.cache/jetbrains-pycharm.XXXXXX")"
  trap 'rm -rf "$tmp_dir"' EXIT

  archive="$tmp_dir/pycharm-${PYCHARM_VERSION}-aarch64.tar.gz"
  setup_log "Downloading PyCharm archive"
  curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 --progress-bar -o "$archive" "$PYCHARM_LINUX_ARM64_URL"

  setup_log "Verifying PyCharm archive checksum"
  printf '%s  %s\n' "$PYCHARM_LINUX_ARM64_SHA" "$archive" | sha256sum -c -

  setup_log "Extracting PyCharm archive"
  tar -xzf "$archive" -C "$tmp_dir"
  extracted_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ -z "$extracted_dir" ]; then
    echo "PyCharm archive did not contain a top-level directory" >&2
    exit 1
  fi

  setup_log "Installing PyCharm backend into $pycharm_dir"
  rm -rf "$pycharm_dir"
  mv "$extracted_dir" "$pycharm_dir"
  touch "$pycharm_dir/.coder-preinstalled"

  rm -rf "$tmp_dir"
  trap - EXIT
  setup_log "PyCharm backend install complete"
else
  setup_log "PyCharm backend already installed at $pycharm_dir; skipping download"
fi

configure_pycharm_runtime
configure_pycharm_default_project "$pycharm_project_dir"

setup_log "Registering PyCharm backend for JetBrains Gateway"
if timeout 90 "$pycharm_dir/bin/remote-dev-server.sh" registerBackendLocationForGateway >/tmp/pycharm-register.log 2>&1; then
  setup_log "PyCharm backend registration complete"
else
  register_status="$?"
  if [ "$register_status" -eq 124 ]; then
    setup_log "PyCharm backend registration timed out after 90 seconds; continuing"
  else
    setup_log "PyCharm backend registration reported an error; continuing"
  fi
  cat /tmp/pycharm-register.log
fi
