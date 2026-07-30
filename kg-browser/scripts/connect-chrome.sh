#!/usr/bin/env bash
#
# 把 chrome-devtools CLI daemon 连接到「用户可见的真实 Chrome」。
#
# 为什么要连真实 Chrome 而不是起一个干净实例：
#   · 天然带用户已有的登录态（知乎/内网文档等无需再配 cookie）
#   · 天然通过站点的 JS 挑战（如知乎 zse-ck）——因为就是真浏览器在跑
#   · 不做任何 cookie 注入/伪造，只读用户自己已经能看到的页面
#
# 前置：
#   1. npm i -g chrome-devtools-mcp@latest
#   2. Chrome 开启 remote debugging（见下方 guide，一次性）
#
# 用法：bash scripts/connect-chrome.sh
# 成功后即可使用 chrome-devtools 各命令（navigate_page / evaluate_script 等）。

set -euo pipefail

# ---------- 按平台定位 Chrome 的 DevToolsActivePort ----------
# 该文件由 Chrome 在开启 remote debugging 后写入，含端口和 ws 路径。
detect_devtools_file() {
  if [[ -n "${CHROME_DEVTOOLS_ACTIVE_PORT_FILE:-}" ]]; then
    printf '%s\n' "$CHROME_DEVTOOLS_ACTIVE_PORT_FILE"; return
  fi

  local uname_s; uname_s="$(uname -s)"
  local is_wsl=0
  [[ "$uname_s" == "Linux" ]] && grep -qi microsoft /proc/version 2>/dev/null && is_wsl=1

  local candidates=()
  if [[ "$uname_s" == "Darwin" ]]; then
    candidates+=("$HOME/Library/Application Support/Google/Chrome/DevToolsActivePort")
  elif ((is_wsl)); then
    # WSL：Chrome 在 Windows 侧，遍历 /mnt/c/Users/*/
    if [[ -d /mnt/c/Users ]]; then
      for udir in /mnt/c/Users/*/; do
        [[ -d "$udir" ]] || continue   # glob 未匹配时原样留 * ,这里挡掉
        local uname_base; uname_base="$(basename "$udir")"
        case "$uname_base" in Public|Default|"Default User"|"All Users") continue ;; esac
        candidates+=("${udir}AppData/Local/Google/Chrome/User Data/DevToolsActivePort")
      done
    fi
    # WSL 里也可能装了 Linux 版 Chrome
    candidates+=("$HOME/.config/google-chrome/DevToolsActivePort")
  else
    candidates+=("$HOME/.config/google-chrome/DevToolsActivePort")
    candidates+=("$HOME/.config/chromium/DevToolsActivePort")
  fi

  for c in "${candidates[@]}"; do
    [[ -f "$c" ]] && { printf '%s\n' "$c"; return; }
  done
  # 都没找到，返回第一个候选用于报错信息
  printf '%s\n' "${candidates[0]:-}"
}

DEVTOOLS_FILE="$(detect_devtools_file)"

IS_WSL=0
[[ "$(uname -s)" == "Linux" ]] && grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1
CONNECT_ATTEMPTS="${CHROME_DEVTOOLS_CONNECT_ATTEMPTS:-6}"
CONNECT_DELAY_SECONDS="${CHROME_DEVTOOLS_CONNECT_DELAY_SECONDS:-2}"
MAX_RESTARTS="${CHROME_DEVTOOLS_MAX_RESTARTS:-3}"

REMOTE_DEBUGGING_GUIDE='Chrome remote debugging 手动开启步骤：
1. 打开 Chrome。
2. 访问 chrome://inspect/#remote-debugging。
3. 勾选 "Allow remote debugging for this browser instance"。
4. 彻底关闭 Chrome。
5. 重新打开 Chrome。
6. 重新执行本脚本 bash scripts/connect-chrome.sh。'

WSL_GUIDE='WSL 额外说明（重要）：
Chrome 跑在 Windows 侧，而本脚本跑在 WSL 里，两者网络命名空间不同——
ws://127.0.0.1:<port> 在 WSL 里指向 WSL 自己，连不到 Windows 的 Chrome。

三种可行做法：
  A) 在 Windows 侧启动 Chrome 时显式监听所有网卡（推荐）：
       chrome.exe --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0
     然后在 WSL 里指定 Windows 主机 IP：
       WIN_IP=$(ip route show default | awk "{print \$3}")
       chrome-devtools start --wsEndpoint "ws://$WIN_IP:9222/devtools/browser/<id>" --no-headless
     （<id> 从 http://$WIN_IP:9222/json/version 的 webSocketDebuggerUrl 取）

  B) 在 WSL 里装 Linux 版 Chrome + WSLg 图形界面，全部在 WSL 内完成
     （缺点：登录态与你平时用的 Windows Chrome 不共享）

  C) 该 skill 的浏览器功能改在 Windows 侧跑（把仓库放 Windows 侧用原生 Python）

如果只是想读历史/书签（不需要实时操作浏览器），
用 find-history.py 即可——它能直接穿 /mnt/c 读 Windows 侧的 Chrome 数据，无需 debugging。'

fail_with_guide() {
  local message="$1"
  echo "Error: $message" >&2
  echo "" >&2
  echo "$REMOTE_DEBUGGING_GUIDE" >&2
  if ((IS_WSL)); then
    echo "" >&2
    echo "$WSL_GUIDE" >&2
  fi
  exit 1
}

if ! command -v chrome-devtools >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Error: 未找到 chrome-devtools 命令。
请先安装 CLI：

  npm i chrome-devtools-mcp@latest -g
EOF
  exit 1
fi

read_ws_endpoint() {
  local port
  local ws_path

  if [[ ! -f "$DEVTOOLS_FILE" ]]; then
    fail_with_guide "Chrome DevToolsActivePort file not found: $DEVTOOLS_FILE"
  fi

  port="$(sed -n '1p' "$DEVTOOLS_FILE")"
  ws_path="$(sed -n '2p' "$DEVTOOLS_FILE")"

  if [[ -z "$port" || -z "$ws_path" ]]; then
    fail_with_guide "Failed to read Chrome debugging info from $DEVTOOLS_FILE"
  fi

  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    fail_with_guide "Invalid Chrome debugging port in $DEVTOOLS_FILE: $port"
  fi

  printf 'ws://127.0.0.1:%s%s\n' "$port" "$ws_path"
}

start_daemon() {
  local endpoint="$1"

  chrome-devtools stop >/dev/null 2>&1 || true
  # --no-headless：必须连有界面的真实 Chrome（headless 拿不到用户登录态）。
  if ! chrome-devtools start \
    --wsEndpoint "$endpoint" \
    --no-headless >/dev/null 2>&1; then
    return 1
  fi
}

WS_ENDPOINT="$(read_ws_endpoint)"
restart_count=1

while ((restart_count <= MAX_RESTARTS)); do
  echo "Connecting chrome-devtools CLI daemon to user Chrome:"
  echo "  $WS_ENDPOINT"

  if ! start_daemon "$WS_ENDPOINT"; then
    fail_with_guide "Failed to start chrome-devtools daemon for user Chrome"
  fi

  attempt=1
  while ((attempt <= CONNECT_ATTEMPTS)); do
    sleep "$CONNECT_DELAY_SECONDS"

    latest_endpoint="$(read_ws_endpoint)"
    if [[ "$latest_endpoint" != "$WS_ENDPOINT" ]]; then
      echo "Chrome debugging endpoint changed; reconnecting."
      WS_ENDPOINT="$latest_endpoint"
      break
    fi

    status_output="$(chrome-devtools status 2>&1 || true)"
    if [[ "$status_output" != *"$WS_ENDPOINT"* ]]; then
      ((attempt += 1))
      continue
    fi

    pages_output="$(chrome-devtools list_pages 2>&1 || true)"
    status_after_pages="$(chrome-devtools status 2>&1 || true)"
    if [[ "$pages_output" == *"## Pages"* && "$status_after_pages" == *"$WS_ENDPOINT"* ]]; then
      echo "Connected to user Chrome."
      printf '%s\n' "$pages_output"
      exit 0
    fi

    ((attempt += 1))
  done

  ((restart_count += 1))
done

chrome-devtools stop >/dev/null 2>&1 || true
fail_with_guide "User Chrome connection did not become ready after ${MAX_RESTARTS} restart attempts"
