terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

provider "coder" {}

variable "use_kubeconfig" {
  type        = bool
  description = "Use ~/.kube/config instead of the in-cluster service account."
  default     = false
}

variable "storage_class" {
  type        = string
  description = "StorageClass used for workspace home PVCs."
  default     = "longhorn"
}

variable "image_pull_secret" {
  type        = string
  description = "Optional Kubernetes imagePullSecret name for private GHCR images."
  default     = ""
}

data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}
data "coder_provisioner" "me" {}

data "coder_parameter" "repo_url" {
  name         = "repo_url"
  display_name = "Git Repository"
  description  = "Optional repository URL to clone into ~/work on first start."
  default      = ""
  mutable      = false
  order        = 10
}

data "coder_parameter" "dotfiles_uri" {
  name         = "dotfiles_uri"
  display_name = "Dotfiles URL"
  description  = "Dotfiles repository applied during workspace setup."
  default      = "https://github.com/abhi1693/dotfiles-coder"
  mutable      = true
  order        = 30
  icon         = "/icon/dotfiles.svg"

  validation {
    regex = "^$|^(https?://|ssh://|git@|git://)[a-zA-Z0-9._/:@~-]+$"
    error = "Must be a valid dotfiles repository URL (https, git@, or git://) without special characters."
  }
}

data "coder_parameter" "dotfiles_branch" {
  name         = "dotfiles_branch"
  display_name = "Dotfiles Branch"
  description  = "Branch to use for the dotfiles repository."
  default      = "master"
  mutable      = true
  order        = 40
  icon         = "/icon/dotfiles.svg"

  validation {
    regex = "^[^\\s]+$"
    error = "Dotfiles branch cannot be empty or contain whitespace."
  }
}

data "coder_parameter" "cpu" {
  name         = "cpu"
  display_name = "CPU"
  description  = "CPU core limit for the workspace pod."
  default      = "1"
  mutable      = true
  order        = 100
  option {
    name  = "1 Core"
    value = "1"
  }
  option {
    name  = "2 Cores"
    value = "2"
  }
  option {
    name  = "4 Cores"
    value = "4"
  }
}

data "coder_parameter" "memory" {
  name         = "memory"
  display_name = "Memory"
  description  = "Memory limit for the workspace pod."
  default      = "1"
  mutable      = true
  order        = 110
  option {
    name  = "1 GiB"
    value = "1"
  }
  option {
    name  = "2 GiB"
    value = "2"
  }
  option {
    name  = "4 GiB"
    value = "4"
  }
  option {
    name  = "8 GiB"
    value = "8"
  }
}

data "coder_parameter" "home_disk_size" {
  name         = "home_disk_size"
  display_name = "Home Disk"
  description  = "Persistent home volume size in GiB."
  type         = "number"
  default      = "20"
  mutable      = true
  order        = 120
  validation {
    min = 5
    max = 200
  }
}

data "coder_parameter" "enable_dind" {
  name         = "enable_dind"
  display_name = "Docker Sidecar"
  description  = "Run a privileged Docker-in-Docker sidecar and let dotfiles install Docker client tooling."
  type         = "bool"
  default      = "true"
  mutable      = true
  order        = 200
}

data "coder_parameter" "enable_postgres" {
  name         = "enable_postgres"
  display_name = "PostgreSQL"
  description  = "Run a private single-instance CloudNativePG PostgreSQL service for this workspace."
  type         = "bool"
  default      = "false"
  mutable      = true
  order        = 210
}

data "coder_parameter" "enable_redis" {
  name         = "enable_redis"
  display_name = "Redis"
  description  = "Run a private standalone Redis service for this workspace."
  type         = "bool"
  default      = "false"
  mutable      = true
  order        = 220
}

data "coder_external_auth" "github" {
  count = can(regex("^https://github\\.com/", data.coder_parameter.repo_url.value)) ? 1 : 0

  id = "github"
}

provider "kubernetes" {
  config_path = var.use_kubeconfig ? "~/.kube/config" : null
}

locals {
  template_name       = "python-3-12"
  workspace_namespace = "coder-workspaces"
  workspace_image     = "ghcr.io/abhi1693/home-lab:python-3-12-13052026"
  workspace_bootstrap_packages = [
    "build-essential",
    "curl",
    "git",
    "jq",
    "libffi-dev",
    "libfreetype-dev",
    "libjpeg-dev",
    "liblcms2-dev",
    "libldap2-dev",
    "libpq-dev",
    "libsasl2-dev",
    "libssl-dev",
    "libwebp-dev",
    "libxml2-dev",
    "libxslt1-dev",
    "pkg-config",
    "pipx",
    "python-is-python3",
    "python3",
    "python3.12-dev",
    "python3-dev",
    "python3-pip",
    "python3-venv",
    "tk-dev",
    "zsh",
  ]
  dind_image               = "docker:29-dind"
  workspace_cpu_request    = "500m"
  workspace_memory_request = "512Mi"
  pycharm_version          = "2026.1.1"
  pycharm_build            = "261.23567.174"
  pycharm_linux_arm64_url  = "https://download.jetbrains.com/python/pycharm-2026.1.1-aarch64.tar.gz"
  pycharm_linux_arm64_sha  = "d777036e072628beac6f5300149fdef26e83351dbd84c399476ba8da209a0eaa"
  pycharm_heap_mb          = tonumber(data.coder_parameter.memory.value) >= 8 ? 2048 : tonumber(data.coder_parameter.memory.value) >= 4 ? 1536 : tonumber(data.coder_parameter.memory.value) >= 2 ? 1024 : 768
  owner_name               = replace(lower(data.coder_workspace_owner.me.name), "/[^a-z0-9-]/", "-")
  workspace_name           = replace(lower(data.coder_workspace.me.name), "/[^a-z0-9-]/", "-")
  name                     = trimsuffix(substr("coder-${local.owner_name}-${local.workspace_name}", 0, 63), "-")
  workspace_user           = local.owner_name
  workspace_uid            = 1001
  workspace_home           = "/home/${local.workspace_user}"
  workspace_repo_dir       = "${local.workspace_home}/work"
  jetbrains_project_dir    = data.coder_parameter.repo_url.value != "" ? local.workspace_repo_dir : local.workspace_home
  pycharm_config_dir       = "PyCharm2026.1"
  nodejs_version           = "22"
  docker_enabled           = data.coder_parameter.enable_dind.value == "true"
  postgres_enabled         = data.coder_parameter.enable_postgres.value == "true"
  redis_enabled            = data.coder_parameter.enable_redis.value == "true"
  nodejs_running           = data.coder_workspace.me.start_count != 0
  postgres_running         = data.coder_workspace.me.start_count != 0 && local.postgres_enabled
  redis_running            = data.coder_workspace.me.start_count != 0 && local.redis_enabled
  postgres_name            = trimsuffix(substr("pg-${local.owner_name}-${local.workspace_name}", 0, 63), "-")
  postgres_secret_name     = trimsuffix(substr("${local.postgres_name}-app", 0, 63), "-")
  postgres_database        = "workspace"
  postgres_username        = "workspace"
  postgres_port            = 5432
  postgres_host            = "${local.postgres_name}-rw.${local.workspace_namespace}.svc.cluster.local"
  redis_name               = trimsuffix(substr("redis-${local.owner_name}-${local.workspace_name}", 0, 63), "-")
  redis_secret_name        = trimsuffix(substr("${local.redis_name}-auth", 0, 63), "-")
  redis_username           = "default"
  redis_port               = 6379
  redis_host               = "${local.redis_name}.${local.workspace_namespace}.svc.cluster.local"
  service_credentials_port = 43857
  agent_preserve_env = join(",", [
    "CODER_AGENT_DEVCONTAINERS_ENABLE",
    "CODER_AGENT_TOKEN",
    "DATABASE_URL",
    "DOCKER_HOST",
    "DOCKER_TLS_CERTDIR",
    "PGDATABASE",
    "PGHOST",
    "PGPASSWORD",
    "PGPORT",
    "PGUSER",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "POSTGRES_URL",
    "POSTGRES_USER",
    "REDIS_HOST",
    "REDIS_PASSWORD",
    "REDIS_PORT",
    "REDIS_USERNAME",
    "REDIS_URL",
    "REMOTE_DEV_TRUST_PROJECTS",
    "SKIP_DOCKER_INSTALL",
  ])

  workspace_labels = {
    "app.kubernetes.io/name"     = "coder-workspace"
    "app.kubernetes.io/instance" = local.name
  }

  common_labels = merge(local.workspace_labels, {
    "app.kubernetes.io/component"    = "workspace"
    "app.kubernetes.io/managed-by"   = "coder"
    "app.kubernetes.io/part-of"      = "coder"
    "coder.com/workspace"            = data.coder_workspace.me.name
    "coder.com/workspace-owner"      = data.coder_workspace_owner.me.name
    "coder.com/workspace-template"   = local.template_name
    "coder.com/workspace-started-by" = data.coder_workspace_owner.me.name
  })
}

resource "coder_agent" "main" {
  os   = "linux"
  arch = data.coder_provisioner.me.arch
  dir  = local.workspace_home

  env = merge(
    {
      CODER_AGENT_DEVCONTAINERS_ENABLE = "false"
      HOME                             = local.workspace_home
      LOGNAME                          = local.workspace_user
      REMOTE_DEV_TRUST_PROJECTS        = "1"
      SKIP_DOCKER_INSTALL              = local.docker_enabled ? "0" : "1"
      SHELL                            = "/usr/bin/zsh"
      USER                             = local.workspace_user
    },
    local.docker_enabled ? {
      DOCKER_HOST        = "tcp://localhost:2375"
      DOCKER_TLS_CERTDIR = ""
    } : {}
  )

  display_apps {
    vscode                 = false
    vscode_insiders        = false
    ssh_helper             = true
    port_forwarding_helper = true
    web_terminal           = true
  }

  startup_script = <<-EOT
    #!/usr/bin/env bash
    set -euo pipefail

    export PYCHARM_VERSION=${jsonencode(local.pycharm_version)}
    export PYCHARM_BUILD=${jsonencode(local.pycharm_build)}
    export PYCHARM_LINUX_ARM64_URL=${jsonencode(local.pycharm_linux_arm64_url)}
    export PYCHARM_LINUX_ARM64_SHA=${jsonencode(local.pycharm_linux_arm64_sha)}
    export PYCHARM_HEAP_MB=${jsonencode(local.pycharm_heap_mb)}
    export PYCHARM_CONFIG_DIR=${jsonencode(local.pycharm_config_dir)}
    export PYCHARM_PROJECT_DIR=${jsonencode(local.jetbrains_project_dir)}
    export WORKSPACE_REPO_URL_B64=${jsonencode(base64encode(data.coder_parameter.repo_url.value))}

    ${file("${path.module}/shared/scripts/setup-pycharm.sh")}
  EOT

  metadata {
    display_name = "CPU Usage"
    key          = "0_cpu_usage"
    script       = "coder stat cpu"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "RAM Usage"
    key          = "1_ram_usage"
    script       = "coder stat mem"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Home Disk"
    key          = "3_home_disk"
    script       = "coder stat disk --path $${HOME}"
    interval     = 60
    timeout      = 1
  }

  metadata {
    display_name = "CPU Usage (Host)"
    key          = "4_cpu_usage_host"
    script       = "coder stat cpu --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Memory Usage (Host)"
    key          = "5_mem_usage_host"
    script       = "coder stat mem --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Load Average (Host)"
    key          = "6_load_host"
    script       = <<EOT
      echo "`cat /proc/loadavg | awk '{ print $1 }'` `nproc`" | awk '{ printf "%0.2f", $1/$2 }'
    EOT
    interval     = 60
    timeout      = 1
  }
}

module "coder_login" {
  count = data.coder_workspace.me.start_count

  source  = "registry.coder.com/coder/coder-login/coder"
  version = "1.1.1"

  agent_id = coder_agent.main.id
}

module "git_config" {
  count = data.coder_workspace.me.start_count

  source  = "registry.coder.com/coder/git-config/coder"
  version = "1.0.33"

  agent_id              = coder_agent.main.id
  allow_username_change = false
  allow_email_change    = false
}

module "git_commit_signing" {
  count = data.coder_workspace.me.start_count

  source  = "registry.coder.com/coder/git-commit-signing/coder"
  version = "1.0.32"

  agent_id = coder_agent.main.id
}

module "git_clone" {
  count = data.coder_workspace.me.start_count == 1 && data.coder_parameter.repo_url.value != "" ? 1 : 0

  source  = "registry.coder.com/coder/git-clone/coder"
  version = "1.2.3"

  agent_id    = coder_agent.main.id
  url         = data.coder_parameter.repo_url.value
  base_dir    = local.workspace_home
  folder_name = "work"
  depth       = 1

  depends_on = [data.coder_external_auth.github]
}

module "jetbrains" {
  count = data.coder_workspace.me.start_count

  source  = "registry.coder.com/coder/jetbrains/coder"
  version = "1.4.0"

  agent_id = coder_agent.main.id
  folder   = local.jetbrains_project_dir
  default  = ["PY"]
  options  = ["PY"]
  tooltip  = "PyCharm Professional ${local.pycharm_version} is preloaded in the workspace; install JetBrains Toolbox 2.7+ locally to launch it."

  ide_config = {
    PY = {
      build = local.pycharm_build
    }
  }

  coder_app_order = 10
}

module "filebrowser" {
  count = data.coder_workspace.me.start_count

  source  = "registry.coder.com/coder/filebrowser/coder"
  version = "1.1.4"

  agent_id      = coder_agent.main.id
  agent_name    = "main"
  folder        = local.workspace_home
  database_path = "${local.workspace_home}/filebrowser.db"
  subdomain     = false
  order         = 20
}

resource "coder_script" "service_credentials" {
  count = data.coder_workspace.me.start_count

  agent_id     = coder_agent.main.id
  display_name = "Service Credentials"
  icon         = "/icon/database.svg"
  run_on_start = true

  script = <<-EOT
    #!/usr/bin/env sh
    set -eu

    state_dir="$HOME/.cache/coder/service-credentials"
    server_file="$state_dir/server.py"
    pid_file="$state_dir/server.pid"
    log_file="$state_dir/server.log"

    mkdir -p "$state_dir"

    if curl -fsS "http://127.0.0.1:${local.service_credentials_port}/health" >/dev/null 2>&1; then
      exit 0
    fi
    rm -f "$pid_file"

    cat > "$server_file" <<'PY'
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ["SERVICE_CREDENTIALS_PORT"])

def value(name, default=""):
    return os.environ.get(name) or default

def row(label, env_var, text, secret=False):
    env_name = html.escape(env_var)
    escaped = html.escape(text)
    class_name = " secret" if secret else ""
    return (
        f"<tr><th scope='row'>{html.escape(label)}</th>"
        f"<td class='mono env'>{env_name}</td>"
        f"<td class='mono{class_name}'>{escaped}</td></tr>"
    )

def section(title, rows):
    return (
        f"<section><h2>{html.escape(title)}</h2>"
        "<table><thead><tr><th>Field</th><th>Env var</th><th>Value</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )

def page():
    pg_enabled = bool(value("PGHOST"))
    redis_enabled = bool(value("REDIS_HOST"))
    pg_rows = [
        row("Status", "PGHOST", "enabled" if pg_enabled else "disabled"),
        row("Host", "PGHOST", value("PGHOST")),
        row("Port", "PGPORT", value("PGPORT")),
        row("Database", "PGDATABASE", value("PGDATABASE")),
        row("Username", "PGUSER", value("PGUSER")),
        row("Password", "PGPASSWORD", value("PGPASSWORD"), True),
        row("URL", "DATABASE_URL", value("DATABASE_URL"), True),
        row("Command", "DATABASE_URL", f'psql "{value("DATABASE_URL")}"', True),
    ]
    redis_rows = [
        row("Status", "REDIS_HOST", "enabled" if redis_enabled else "disabled"),
        row("Host", "REDIS_HOST", value("REDIS_HOST")),
        row("Port", "REDIS_PORT", value("REDIS_PORT")),
        row("Username", "REDIS_USERNAME", value("REDIS_USERNAME", "default")),
        row("Password", "REDIS_PASSWORD", value("REDIS_PASSWORD"), True),
        row("URL", "REDIS_URL", value("REDIS_URL"), True),
        row("Command", "REDIS_URL", f'redis-cli -u "{value("REDIS_URL")}"', True),
    ]
    body = section("PostgreSQL", pg_rows) + section("Redis", redis_rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Service Credentials</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; background: #0f172a; color: #e5e7eb; }}
    main {{ max-width: 960px; margin: 0 auto; padding: 32px 20px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; }}
    p {{ color: #94a3b8; margin: 0 0 24px; }}
    section {{ border: 1px solid #334155; border-radius: 8px; margin: 18px 0; overflow: hidden; background: #111827; }}
    h2 {{ font-size: 18px; margin: 0; padding: 14px 16px; border-bottom: 1px solid #334155; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 12px 16px; border-top: 1px solid #1f2937; text-align: left; vertical-align: top; }}
    thead th {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
    tbody th {{ width: 150px; color: #cbd5e1; font-weight: 600; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; word-break: break-all; }}
    .env {{ width: 170px; color: #93c5fd; }}
    .secret {{ color: #fbbf24; }}
  </style>
</head>
<body>
  <main>
    <h1>Service Credentials</h1>
    <p>Generated for this Coder workspace and injected into the dev container environment.</p>
    {body}
  </main>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            data = b"ok\n"
            self.send_response(200)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        data = page().encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return

ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
PY

    SERVICE_CREDENTIALS_PORT=${local.service_credentials_port} nohup python3 -u "$server_file" >"$log_file" 2>&1 &
    echo "$!" > "$pid_file"

    for _ in $(seq 1 20); do
      if curl -fsS "http://127.0.0.1:${local.service_credentials_port}/health" >/dev/null 2>&1; then
        exit 0
      fi
      sleep 0.5
    done

    cat "$log_file" >&2
    exit 1
  EOT
}

resource "coder_app" "service_credentials" {
  count = data.coder_workspace.me.start_count

  agent_id     = coder_agent.main.id
  display_name = "Service Credentials"
  slug         = "service-credentials"
  url          = "http://127.0.0.1:${local.service_credentials_port}"
  icon         = "/icon/database.svg"
  order        = 30
  subdomain    = false

  healthcheck {
    url       = "http://127.0.0.1:${local.service_credentials_port}/health"
    interval  = 5
    threshold = 6
  }
}

resource "coder_script" "nodejs_shell" {
  count = local.nodejs_running ? 1 : 0

  agent_id           = coder_agent.main.id
  display_name       = "Node.js Shell"
  run_on_start       = true
  start_blocks_login = true

  script = <<-EOT
    #!/usr/bin/env bash
    export EXPECTED_NODE_VERSION=${jsonencode(local.nodejs_version)}

    ${file("${path.module}/shared/scripts/setup-node-codex.sh")}
  EOT
}

module "dotfiles" {
  count = data.coder_workspace.me.start_count

  source  = "registry.coder.com/coder/dotfiles/coder"
  version = "1.4.1"

  agent_id        = coder_agent.main.id
  dotfiles_uri    = data.coder_parameter.dotfiles_uri.value
  dotfiles_branch = data.coder_parameter.dotfiles_branch.value
  manual_update   = true
  order           = 50
}

resource "kubernetes_persistent_volume_claim_v1" "home" {
  metadata {
    name      = "${local.name}-home"
    namespace = local.workspace_namespace
    labels    = local.common_labels
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class
    resources {
      requests = {
        storage = "${data.coder_parameter.home_disk_size.value}Gi"
      }
    }
  }
}

resource "kubernetes_pod_v1" "workspace" {
  count = data.coder_workspace.me.start_count

  metadata {
    name      = local.name
    namespace = local.workspace_namespace
    labels    = local.common_labels
    annotations = {
      "cluster-autoscaler.kubernetes.io/safe-to-evict" = "false"
    }
  }

  spec {
    automount_service_account_token  = false
    node_selector                    = { "kubernetes.io/arch" = "arm64" }
    restart_policy                   = "Always"
    termination_grace_period_seconds = 60

    dynamic "image_pull_secrets" {
      for_each = var.image_pull_secret == "" ? [] : [var.image_pull_secret]

      content {
        name = image_pull_secrets.value
      }
    }

    security_context {
      run_as_user            = 1000
      run_as_group           = 1000
      fs_group               = local.workspace_uid
      fs_group_change_policy = "OnRootMismatch"

      seccomp_profile {
        type = "RuntimeDefault"
      }
    }

    container {
      name              = "dev"
      image             = local.workspace_image
      image_pull_policy = "IfNotPresent"
      command = ["sh", "-c", <<-EOF
        set -eu

        workspace_user="${local.workspace_user}"
        workspace_uid="${local.workspace_uid}"
        workspace_home="${local.workspace_home}"

        missing_packages=""
        for package in ${join(" ", local.workspace_bootstrap_packages)}; do
          if ! dpkg-query -W -f='$${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed'; then
            missing_packages="$missing_packages $package"
          fi
        done
        if [ -n "$missing_packages" ]; then
          sudo apt-get update -yq
          sudo env DEBIAN_FRONTEND=noninteractive apt-get install -yq $missing_packages
        fi

        if ! id -u "$workspace_user" >/dev/null 2>&1; then
          sudo useradd "$workspace_user" --home-dir "$workspace_home" --shell=/bin/bash --uid="$workspace_uid" --user-group
        fi

        sudo mkdir -p "$workspace_home"
        workspace_gid="$(id -g "$workspace_user")"
        if [ "$(stat -c '%u:%g' "$workspace_home")" != "$workspace_uid:$workspace_gid" ]; then
          sudo chown -R "$workspace_user:$workspace_user" "$workspace_home"
        fi
        printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$workspace_user" | sudo tee /etc/sudoers.d/coder-workspace-user >/dev/null
        sudo chmod 0440 /etc/sudoers.d/coder-workspace-user

        zsh_path="$(command -v zsh || true)"
        if [ -n "$zsh_path" ]; then
          if [ -f /etc/shells ] && ! grep -qxF "$zsh_path" /etc/shells; then
            echo "$zsh_path" | sudo tee -a /etc/shells >/dev/null
          fi
          sudo usermod -s "$zsh_path" "$workspace_user"
        fi

        user_path="$workspace_home/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        if ! sudo -H -u "$workspace_user" env HOME="$workspace_home" PATH="$user_path" sh -lc 'command -v uv >/dev/null 2>&1 && command -v uvx >/dev/null 2>&1'; then
          sudo mkdir -p "$workspace_home/.local/bin"
          sudo chown -R "$workspace_user:$workspace_user" "$workspace_home/.local"
          uv_installer="$(mktemp)"
          curl -LsSf https://astral.sh/uv/install.sh -o "$uv_installer"
          chmod 0644 "$uv_installer"
          sudo -H -u "$workspace_user" env HOME="$workspace_home" PATH="$user_path" UV_INSTALL_DIR="$workspace_home/.local/bin" sh "$uv_installer"
          rm -f "$uv_installer"
        fi
        sudo -H -u "$workspace_user" env HOME="$workspace_home" PATH="$user_path" python3 -m pipx ensurepath >/dev/null 2>&1 || true
        if sudo test -x "$workspace_home/.local/bin/uv"; then
          sudo install -m 0755 "$workspace_home/.local/bin/uv" /usr/local/bin/uv
        fi
        if sudo test -x "$workspace_home/.local/bin/uvx"; then
          sudo install -m 0755 "$workspace_home/.local/bin/uvx" /usr/local/bin/uvx
        fi

        agent_script="$(mktemp)"
        printf '%s' '${base64encode(coder_agent.main.init_script)}' | base64 -d > "$agent_script"
        chmod 0755 "$agent_script"

        exec sudo --preserve-env=${local.agent_preserve_env} -H -u "$workspace_user" env HOME="$workspace_home" USER="$workspace_user" LOGNAME="$workspace_user" SHELL=/usr/bin/zsh sh "$agent_script"
      EOF
      ]
      working_dir = "/tmp"

      env {
        name  = "CODER_AGENT_TOKEN"
        value = coder_agent.main.token
      }

      env {
        name  = "HOME"
        value = local.workspace_home
      }

      env {
        name  = "USER"
        value = local.workspace_user
      }

      env {
        name  = "LOGNAME"
        value = local.workspace_user
      }

      env {
        name  = "SHELL"
        value = "/usr/bin/zsh"
      }

      env {
        name  = "SKIP_DOCKER_INSTALL"
        value = local.docker_enabled ? "0" : "1"
      }

      env {
        name  = "CODER_AGENT_DEVCONTAINERS_ENABLE"
        value = "false"
      }

      dynamic "env" {
        for_each = local.docker_enabled ? {
          DOCKER_HOST        = "tcp://localhost:2375"
          DOCKER_TLS_CERTDIR = ""
        } : {}

        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env_from" {
        for_each = local.postgres_running ? [kubernetes_secret_v1.postgres[0].metadata[0].name] : []
        iterator = postgres_secret

        content {
          secret_ref {
            name = postgres_secret.value
          }
        }
      }

      dynamic "env_from" {
        for_each = local.redis_running ? [kubernetes_secret_v1.redis[0].metadata[0].name] : []
        iterator = redis_secret

        content {
          secret_ref {
            name = redis_secret.value
          }
        }
      }

      resources {
        requests = {
          cpu    = local.workspace_cpu_request
          memory = local.workspace_memory_request
        }
        limits = {
          cpu    = data.coder_parameter.cpu.value
          memory = "${data.coder_parameter.memory.value}Gi"
        }
      }

      security_context {
        allow_privilege_escalation = true
        privileged                 = false
        read_only_root_filesystem  = false
        run_as_group               = 1000
        run_as_non_root            = true
        run_as_user                = 1000
      }

      volume_mount {
        name       = "home"
        mount_path = local.workspace_home
      }
    }

    dynamic "container" {
      for_each = local.docker_enabled ? [1] : []

      content {
        name              = "dind"
        image             = local.dind_image
        image_pull_policy = "IfNotPresent"

        env {
          name  = "DOCKER_TLS_CERTDIR"
          value = ""
        }

        env {
          name  = "DOCKER_DRIVER"
          value = "overlay2"
        }

        port {
          name           = "docker"
          container_port = 2375
          protocol       = "TCP"
        }

        resources {
          requests = {
            cpu    = "100m"
            memory = "256Mi"
          }
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }

        security_context {
          allow_privilege_escalation = true
          privileged                 = true
          read_only_root_filesystem  = false
          run_as_group               = 0
          run_as_non_root            = false
          run_as_user                = 0
        }

        volume_mount {
          name       = "docker-graph-storage"
          mount_path = "/var/lib/docker"
        }
      }
    }

    volume {
      name = "home"
      persistent_volume_claim {
        claim_name = kubernetes_persistent_volume_claim_v1.home.metadata[0].name
      }
    }

    dynamic "volume" {
      for_each = local.docker_enabled ? [1] : []

      content {
        name = "docker-graph-storage"
        empty_dir {}
      }
    }
  }
}

resource "random_password" "postgres" {
  count = local.postgres_enabled ? 1 : 0

  length  = 32
  special = false
}

resource "random_password" "redis" {
  count = local.redis_enabled ? 1 : 0

  length  = 32
  special = false
}

resource "kubernetes_secret_v1" "postgres" {
  count = local.postgres_running ? 1 : 0

  metadata {
    name      = local.postgres_secret_name
    namespace = local.workspace_namespace
    labels = merge(local.common_labels, {
      "app.kubernetes.io/component" = "postgres"
    })
  }

  data = {
    DATABASE_URL      = "postgresql://${local.postgres_username}:${random_password.postgres[0].result}@${local.postgres_host}:${local.postgres_port}/${local.postgres_database}?sslmode=disable"
    PGDATABASE        = local.postgres_database
    PGHOST            = local.postgres_host
    PGPASSWORD        = random_password.postgres[0].result
    PGPORT            = tostring(local.postgres_port)
    PGUSER            = local.postgres_username
    POSTGRES_DB       = local.postgres_database
    POSTGRES_HOST     = local.postgres_host
    POSTGRES_PASSWORD = random_password.postgres[0].result
    POSTGRES_PORT     = tostring(local.postgres_port)
    POSTGRES_URL      = "postgresql://${local.postgres_username}:${random_password.postgres[0].result}@${local.postgres_host}:${local.postgres_port}/${local.postgres_database}?sslmode=disable"
    POSTGRES_USER     = local.postgres_username
    password          = random_password.postgres[0].result
    username          = local.postgres_username
  }

  type = "Opaque"
}

resource "kubernetes_manifest" "postgres" {
  count = local.postgres_running ? 1 : 0

  manifest = {
    apiVersion = "postgresql.cnpg.io/v1"
    kind       = "Cluster"
    metadata = {
      name      = local.postgres_name
      namespace = local.workspace_namespace
      labels = merge(local.common_labels, {
        "app.kubernetes.io/component" = "postgres"
      })
    }
    spec = {
      instances             = 1
      imageName             = "ghcr.io/cloudnative-pg/postgresql:17"
      enableSuperuserAccess = false
      bootstrap = {
        initdb = {
          database = local.postgres_database
          owner    = local.postgres_username
          secret = {
            name = kubernetes_secret_v1.postgres[0].metadata[0].name
          }
        }
      }
      storage = {
        storageClass = var.storage_class
        size         = "1Gi"
      }
      resources = {
        requests = {
          cpu    = "100m"
          memory = "256Mi"
        }
        limits = {
          cpu    = "500m"
          memory = "512Mi"
        }
      }
      affinity = {
        nodeSelector = {
          "kubernetes.io/arch" = "arm64"
        }
      }
    }
  }
}

resource "kubernetes_secret_v1" "redis" {
  count = local.redis_running ? 1 : 0

  metadata {
    name      = local.redis_secret_name
    namespace = local.workspace_namespace
    labels = merge(local.common_labels, {
      "app.kubernetes.io/component" = "redis"
    })
  }

  data = {
    REDIS_HOST     = local.redis_host
    REDIS_PASSWORD = random_password.redis[0].result
    REDIS_PORT     = tostring(local.redis_port)
    REDIS_USERNAME = local.redis_username
    REDIS_URL      = "redis://:${random_password.redis[0].result}@${local.redis_host}:${local.redis_port}/0"
  }

  type = "Opaque"
}

resource "kubernetes_service_v1" "redis" {
  count = local.redis_running ? 1 : 0

  metadata {
    name      = local.redis_name
    namespace = local.workspace_namespace
    labels = merge(local.common_labels, {
      "app.kubernetes.io/component" = "redis"
    })
  }

  spec {
    type = "ClusterIP"
    selector = merge(local.workspace_labels, {
      "app.kubernetes.io/component" = "redis"
    })

    port {
      name        = "redis"
      port        = local.redis_port
      target_port = "redis"
      protocol    = "TCP"
    }
  }
}

resource "kubernetes_pod_v1" "redis" {
  count = local.redis_running ? 1 : 0

  metadata {
    name      = local.redis_name
    namespace = local.workspace_namespace
    labels = merge(local.common_labels, {
      "app.kubernetes.io/component" = "redis"
    })
    annotations = {
      "cluster-autoscaler.kubernetes.io/safe-to-evict" = "true"
    }
  }

  spec {
    automount_service_account_token  = false
    node_selector                    = { "kubernetes.io/arch" = "arm64" }
    restart_policy                   = "Always"
    termination_grace_period_seconds = 30

    security_context {
      run_as_user  = 999
      run_as_group = 999
      fs_group     = 999

      seccomp_profile {
        type = "RuntimeDefault"
      }
    }

    container {
      name              = "redis"
      image             = "redis:7-alpine"
      image_pull_policy = "IfNotPresent"
      args              = ["redis-server", "--appendonly", "yes", "--requirepass", "$(REDIS_PASSWORD)"]

      env {
        name = "REDIS_PASSWORD"
        value_from {
          secret_key_ref {
            name = kubernetes_secret_v1.redis[0].metadata[0].name
            key  = "REDIS_PASSWORD"
          }
        }
      }

      port {
        name           = "redis"
        container_port = local.redis_port
        protocol       = "TCP"
      }

      liveness_probe {
        exec {
          command = ["sh", "-c", "redis-cli -a \"$REDIS_PASSWORD\" ping"]
        }
        initial_delay_seconds = 10
        period_seconds        = 30
        timeout_seconds       = 5
        failure_threshold     = 3
      }

      readiness_probe {
        exec {
          command = ["sh", "-c", "redis-cli -a \"$REDIS_PASSWORD\" ping"]
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        timeout_seconds       = 3
        failure_threshold     = 3
      }

      resources {
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
        limits = {
          cpu    = "500m"
          memory = "256Mi"
        }
      }

      security_context {
        allow_privilege_escalation = false
        privileged                 = false
        read_only_root_filesystem  = false
        run_as_group               = 999
        run_as_non_root            = true
        run_as_user                = 999
      }

      volume_mount {
        name       = "redis-data"
        mount_path = "/data"
      }
    }

    volume {
      name = "redis-data"
      empty_dir {}
    }
  }
}
