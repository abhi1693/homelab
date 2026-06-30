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

data "coder_parameter" "dotfiles_uri" {
  name         = "dotfiles_uri"
  display_name = "Dotfiles URL"
  description  = "Dotfiles repository applied during workspace setup."
  default      = ""
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
  default      = "2"
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
  option {
    name  = "8 Cores"
    value = "8"
  }
}

data "coder_parameter" "memory" {
  name         = "memory"
  display_name = "Memory"
  description  = "Memory limit for the workspace pod."
  default      = "4"
  mutable      = true
  order        = 110
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
  option {
    name  = "16 GiB"
    value = "16"
  }
}

data "coder_parameter" "home_disk_size" {
  name         = "home_disk_size"
  display_name = "Home Disk"
  description  = "Persistent home volume size in GiB."
  type         = "number"
  default      = "40"
  mutable      = true
  order        = 120
  validation {
    min = 10
    max = 500
  }
}

data "coder_parameter" "enable_dind" {
  name         = "enable_dind"
  display_name = "Docker Sidecar"
  description  = "Run a privileged Docker-in-Docker sidecar and let dotfiles install Docker client tooling."
  type         = "bool"
  default      = "false"
  mutable      = true
  order        = 200
}

provider "kubernetes" {
  config_path = var.use_kubeconfig ? "~/.kube/config" : null
}

locals {
  template_name       = "ubuntu-desktop"
  workspace_namespace = "coder-workspaces"
  workspace_image     = "ghcr.io/abhi1693/home-lab:ubuntu-desktop-13052026"
  workspace_required_packages = [
    "adwaita-icon-theme",
    "build-essential",
    "ca-certificates",
    "curl",
    "dbus-x11",
    "desktop-file-utils",
    "fonts-dejavu",
    "fonts-noto-color-emoji",
    "git",
    "gnupg",
    "hicolor-icon-theme",
    "iproute2",
    "jq",
    "less",
    "libasound2t64",
    "libgbm1",
    "libgl1",
    "libgtk-3-0t64",
    "libnss3",
    "libxss1",
    "locales",
    "mousepad",
    "nano",
    "nodejs",
    "openssh-client",
    "pkg-config",
    "procps",
    "python3",
    "python3-pip",
    "ristretto",
    "shared-mime-info",
    "sudo",
    "tango-icon-theme",
    "thunar",
    "tumbler",
    "x11-xserver-utils",
    "xdg-utils",
    "xfce4-panel",
    "xfce4-session",
    "xfce4-settings",
    "xfce4-terminal",
    "xfdesktop4",
    "xfwm4",
    "xterm",
    "zsh",
  ]
  dind_image                  = "docker:29-dind"
  workspace_cpu_request       = "1"
  workspace_memory_request    = "1Gi"
  portabledesktop_version     = "v0.0.8"
  portabledesktop_url         = "https://github.com/coder/portabledesktop/releases/download/v0.0.8/portabledesktop-linux-arm64"
  portabledesktop_sha256      = "749494fc13658a10da2201ed3ea58a858d78fe3fb445132f72dfd797d0d2191e"
  portabledesktop_viewer_port = 6080
  portabledesktop_geometry    = "1440x900"
  owner_name                  = replace(lower(data.coder_workspace_owner.me.name), "/[^a-z0-9-]/", "-")
  workspace_name              = replace(lower(data.coder_workspace.me.name), "/[^a-z0-9-]/", "-")
  name                        = trimsuffix(substr("coder-${local.owner_name}-${local.workspace_name}", 0, 63), "-")
  workspace_user              = local.owner_name
  workspace_uid               = 1001
  workspace_home              = "/home/${local.workspace_user}"
  docker_enabled              = data.coder_parameter.enable_dind.value == "true"
  portabledesktop_running     = data.coder_workspace.me.start_count != 0
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

    mkdir -p "$HOME/.cache/portabledesktop" "$HOME/.local/bin"
    if [ ! -e "$HOME/.zshrc" ]; then
      printf '# Created by the Coder Ubuntu Desktop template.\n' > "$HOME/.zshrc"
    fi
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
    display_name = "Desktop Viewer"
    key          = "2_desktop_viewer"
    script       = "echo http://127.0.0.1:${local.portabledesktop_viewer_port}"
    interval     = 3600
    timeout      = 1
  }

  metadata {
    display_name = "Portable Desktop"
    key          = "3_portable_desktop"
    script       = "portabledesktop info --state-file $${HOME}/.cache/portabledesktop/session.json --json >/dev/null 2>&1 && echo running || echo pending"
    interval     = 3600
    timeout      = 1
  }

  metadata {
    display_name = "Home Disk"
    key          = "4_home_disk"
    script       = "coder stat disk --path $${HOME}"
    interval     = 60
    timeout      = 1
  }

  metadata {
    display_name = "CPU Usage (Host)"
    key          = "5_cpu_usage_host"
    script       = "coder stat cpu --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Memory Usage (Host)"
    key          = "6_mem_usage_host"
    script       = "coder stat mem --host"
    interval     = 10
    timeout      = 1
  }

  metadata {
    display_name = "Load Average (Host)"
    key          = "7_load_host"
    script       = <<EOT
      echo "`cat /proc/loadavg | awk '{ print $1 }'` `nproc`" | awk '{ printf "%0.2f", $1/$2 }'
    EOT
    interval     = 60
    timeout      = 1
  }
}

resource "coder_app" "desktop" {
  count = data.coder_workspace.me.start_count

  agent_id     = coder_agent.main.id
  display_name = "Desktop"
  slug         = "desktop"
  url          = "http://127.0.0.1:${local.portabledesktop_viewer_port}"
  order        = 10
  subdomain    = true

  healthcheck {
    url       = "http://127.0.0.1:${local.portabledesktop_viewer_port}"
    interval  = 5
    threshold = 12
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

resource "coder_script" "codex_shell" {
  count = data.coder_workspace.me.start_count

  agent_id           = coder_agent.main.id
  display_name       = "Codex CLI"
  run_on_start       = true
  start_blocks_login = true

  script = <<-EOT
    #!/usr/bin/env bash
    set -euo pipefail

    command -v node >/dev/null
    node --version
    command -v npm >/dev/null
    npm --version
    command -v codex >/dev/null
    codex --version
  EOT
}

resource "coder_script" "desktop" {
  count = local.portabledesktop_running ? 1 : 0

  agent_id           = coder_agent.main.id
  display_name       = "Portable Desktop"
  run_on_start       = true
  start_blocks_login = true

  script = <<-EOT
    #!/usr/bin/env bash
    set -euo pipefail

    bin_dir="$HOME/.local/bin"
    cache_dir="$HOME/.cache/portabledesktop"
    log_dir="$HOME/.local/state/portabledesktop"
    portabledesktop="$(command -v portabledesktop || true)"
    if [ -z "$portabledesktop" ]; then
      portabledesktop="$bin_dir/portabledesktop"
    fi
    state_file="$cache_dir/session.json"
    session_dir="$cache_dir/session"
    session_flavor="xfce4-v1"
    session_flavor_file="$cache_dir/session-flavor"
    xfce_launcher="$cache_dir/start-xfce.sh"
    xfce_open_log="$log_dir/xfce-open.log"
    xfce_session_log="$log_dir/xfce-session.log"
    viewer_pid_file="$cache_dir/viewer.pid"
    viewer_log="$log_dir/viewer.log"
    up_log="$log_dir/up.log"

    mkdir -p "$bin_dir" "$cache_dir" "$session_dir" "$log_dir"

    install_portabledesktop() {
      tmp="$(mktemp)"
      trap 'rm -f "$tmp"' RETURN
      curl -fsSL --retry 5 --retry-delay 2 -o "$tmp" ${jsonencode(local.portabledesktop_url)}
      printf '%s  %s\n' ${jsonencode(local.portabledesktop_sha256)} "$tmp" | sha256sum -c -
      portabledesktop="$bin_dir/portabledesktop"
      install -m 0755 "$tmp" "$portabledesktop"
      rm -f "$tmp"
      trap - RETURN
    }

    if [ ! -x "$portabledesktop" ] ||
      ! printf '%s  %s\n' ${jsonencode(local.portabledesktop_sha256)} "$portabledesktop" | sha256sum -c - >/dev/null 2>&1; then
      install_portabledesktop
    fi

    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      sudo ln -sfn "$portabledesktop" /usr/local/bin/portabledesktop || true
    fi

    desktop_healthy() {
      local info
      local vnc_port

      info="$("$portabledesktop" info --state-file "$state_file" --json 2>/dev/null)" || return 1
      vnc_port="$(printf '%s' "$info" | jq -r '.vncPort // empty' 2>/dev/null)" || return 1
      [[ "$vnc_port" =~ ^[0-9]+$ ]] || return 1
      timeout 1 bash -c "</dev/tcp/127.0.0.1/$vnc_port" >/dev/null 2>&1
    }

    desktop_environment_healthy() {
      pgrep -u "$(id -u)" -x xfce4-panel >/dev/null 2>&1 &&
        pgrep -u "$(id -u)" -x xfdesktop >/dev/null 2>&1 &&
        pgrep -u "$(id -u)" -x xfwm4 >/dev/null 2>&1
    }

    stop_xfce_processes() {
      pkill -u "$(id -u)" -x xfce4-session >/dev/null 2>&1 || true
      pkill -u "$(id -u)" -x xfwm4 >/dev/null 2>&1 || true
      pkill -u "$(id -u)" -x xfce4-panel >/dev/null 2>&1 || true
      pkill -u "$(id -u)" -x xfdesktop >/dev/null 2>&1 || true
      pkill -u "$(id -u)" -x xfsettingsd >/dev/null 2>&1 || true
      pkill -u "$(id -u)" -x xfconfd >/dev/null 2>&1 || true
    }

    write_xfce_launcher() {
      cat > "$xfce_launcher" <<EOF
#!/usr/bin/env bash
unset SESSION_MANAGER
export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_DESKTOP=xfce
export DESKTOP_SESSION=xfce
export XDG_SESSION_TYPE=x11
exec dbus-run-session -- startxfce4 >>"$xfce_session_log" 2>&1
EOF
      chmod 0755 "$xfce_launcher"
    }

    start_xfce() {
      write_xfce_launcher
      "$portabledesktop" open \
        --state-file "$state_file" \
        --cwd "$HOME" \
        -- "$xfce_launcher" >"$xfce_open_log" 2>&1
    }

    desktop_restarted=0
    if [ "$(cat "$session_flavor_file" 2>/dev/null || true)" != "$session_flavor" ] || ! desktop_healthy; then
      stop_xfce_processes
      "$portabledesktop" down --state-file "$state_file" >/dev/null 2>&1 || true
      rm -f "$state_file"
      rm -f "$xfce_open_log" "$xfce_session_log"
      rm -rf "$session_dir"
      mkdir -p "$session_dir"
      "$portabledesktop" up \
        --json \
        --no-openbox \
        --no-dock \
        --geometry ${jsonencode(local.portabledesktop_geometry)} \
        --state-file "$state_file" \
        --session-dir "$session_dir" >"$up_log" 2>&1
      printf '%s\n' "$session_flavor" > "$session_flavor_file"
      desktop_restarted=1
    fi

    for _ in $(seq 1 30); do
      if desktop_healthy; then
        break
      fi
      sleep 1
    done

    if ! desktop_healthy; then
      cat "$up_log" >&2 || true
      exit 1
    fi

    if [ "$desktop_restarted" -eq 1 ] || ! desktop_environment_healthy; then
      stop_xfce_processes
      start_xfce
    fi

    for _ in $(seq 1 30); do
      if desktop_environment_healthy; then
        break
      fi
      sleep 1
    done

    if ! desktop_environment_healthy; then
      cat "$up_log" >&2 || true
      cat "$xfce_open_log" >&2 || true
      cat "$xfce_session_log" >&2 || true
      exit 1
    fi

    if [ "$desktop_restarted" -eq 1 ] || ! pgrep -u "$(id -u)" -x xfce4-terminal >/dev/null 2>&1; then
      "$portabledesktop" open \
        --state-file "$state_file" \
        --cwd "$HOME" \
        -- xfce4-terminal --working-directory "$HOME" >/dev/null 2>&1 ||
        "$portabledesktop" open \
          --state-file "$state_file" \
          --cwd "$HOME" \
          -- xterm >/dev/null 2>&1 ||
        true
    fi

    viewer_healthy() {
      curl -fsS "http://127.0.0.1:${local.portabledesktop_viewer_port}" >/dev/null 2>&1
    }

    if [ "$desktop_restarted" -eq 1 ] || ! viewer_healthy; then
      if [ -s "$viewer_pid_file" ]; then
        old_pid="$(cat "$viewer_pid_file")"
        kill "$old_pid" >/dev/null 2>&1 || true
      fi
      nohup "$portabledesktop" viewer \
        --host 127.0.0.1 \
        --port ${local.portabledesktop_viewer_port} \
        --no-open \
        --state-file "$state_file" >"$viewer_log" 2>&1 &
      echo "$!" > "$viewer_pid_file"
    fi

    for _ in $(seq 1 30); do
      if viewer_healthy; then
        exit 0
      fi
      sleep 1
    done

    cat "$up_log" >&2 || true
    cat "$viewer_log" >&2 || true
    exit 1
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
      name              = "desktop"
      image             = local.workspace_image
      image_pull_policy = "IfNotPresent"
      command = ["sh", "-c", <<-EOF
        set -eu

        workspace_user="${local.workspace_user}"
        workspace_uid="${local.workspace_uid}"
        workspace_home="${local.workspace_home}"

        missing_packages=""
        for package in ${join(" ", local.workspace_required_packages)}; do
          if ! dpkg-query -W -f='$${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed'; then
            missing_packages="$missing_packages $package"
          fi
        done
        if [ -n "$missing_packages" ]; then
          echo "Workspace image ${local.workspace_image} is missing required package(s):$missing_packages" >&2
          echo "Build and push coder/templates/ubuntu-desktop/image/Dockerfile before starting this template." >&2
          exit 1
        fi

        missing_binaries=""
        for binary in portabledesktop node npm codex startxfce4 xfce4-panel xfdesktop xfwm4; do
          if ! command -v "$binary" >/dev/null 2>&1; then
            missing_binaries="$missing_binaries $binary"
          fi
        done
        if [ -n "$missing_binaries" ]; then
          echo "Workspace image ${local.workspace_image} is missing required command(s):$missing_binaries" >&2
          echo "Build and push coder/templates/ubuntu-desktop/image/Dockerfile before starting this template." >&2
          exit 1
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

      port {
        name           = "desktop"
        container_port = local.portabledesktop_viewer_port
        protocol       = "TCP"
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
