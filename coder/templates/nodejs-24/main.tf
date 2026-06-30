terraform {
  required_providers {
    coder = {
      source = "coder/coder"
    }
    kubernetes = {
      source = "hashicorp/kubernetes"
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

data "coder_external_auth" "github" {
  count = can(regex("^https://github\\.com/", data.coder_parameter.repo_url.value)) ? 1 : 0

  id = "github"
}

provider "kubernetes" {
  config_path = var.use_kubeconfig ? "~/.kube/config" : null
}

locals {
  template_name       = "nodejs-24"
  workspace_namespace = "coder-workspaces"
  workspace_image     = "ghcr.io/abhi1693/home-lab:nodejs-24-13052026"
  workspace_bootstrap_packages = [
    "build-essential",
    "ca-certificates",
    "curl",
    "git",
    "jq",
    "libssl-dev",
    "pkg-config",
    "python3",
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
  nodejs_version           = "24"
  docker_enabled           = data.coder_parameter.enable_dind.value == "true"
  nodejs_running           = data.coder_workspace.me.start_count != 0
  agent_preserve_env = join(",", [
    "CODER_AGENT_DEVCONTAINERS_ENABLE",
    "CODER_AGENT_TOKEN",
    "DOCKER_HOST",
    "DOCKER_TLS_CERTDIR",
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
