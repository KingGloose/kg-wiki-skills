#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_URL = "http://127.0.0.1:10086/command";

function usage() {
  return `用法: node kimi-bridge.mjs <action> --session <任务名> [参数]

常用示例:
  node kimi-bridge.mjs list_tabs --session wiki-capture
  node kimi-bridge.mjs navigate <url> --new-tab --group-title "知识摄入" --session wiki-capture
  node kimi-bridge.mjs find_tab <url> [--active] --session wiki-capture
  node kimi-bridge.mjs snapshot --session wiki-capture
  node kimi-bridge.mjs click <@e-ref|css> --session wiki-capture
  node kimi-bridge.mjs fill <@e-ref|css> <value> --session wiki-capture
  node kimi-bridge.mjs evaluate <javascript> --session wiki-capture
  node kimi-bridge.mjs cdp <method> [params-json] --session wiki-capture
  node kimi-bridge.mjs network <start|stop|list|detail> [filter] --session wiki-capture
  node kimi-bridge.mjs screenshot [--path <file>] [--format png|jpeg] --session wiki-capture
  node kimi-bridge.mjs save_as_pdf [--path <file>] --session wiki-capture
  node kimi-bridge.mjs close_tab --session wiki-capture
  node kimi-bridge.mjs close_session --session wiki-capture

高级用法:
  node kimi-bridge.mjs call <action> '<args-json>' --session wiki-capture`;
}

function parseArgv(argv) {
  const positional = [];
  const options = {};
  const booleans = new Set(["new-tab", "active", "landscape", "print-background"]);
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) {
      positional.push(value);
      continue;
    }
    const key = value.slice(2);
    if (booleans.has(key)) {
      options[key] = true;
      continue;
    }
    if (index + 1 >= argv.length) throw new Error(`--${key} 缺少值`);
    options[key] = argv[++index];
  }
  return { positional, options };
}

function requireValue(value, label) {
  if (value == null || value === "") throw new Error(`${label} 不能为空`);
  return value;
}

function number(value, label) {
  if (value == null) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} 必须是数字`);
  return parsed;
}

export function buildCommand(argv, env = process.env) {
  const { positional, options } = parseArgv(argv);
  let action = positional.shift();
  if (!action) throw new Error(usage());
  const direct = action === "call";
  if (direct) action = requireValue(positional.shift(), "action");
  const session = options.session || env.KIMI_WEBBRIDGE_SESSION;
  if (!session) throw new Error("缺少 --session。同一任务的每次调用必须使用同一个 session 名。");

  if (direct) {
    const raw = positional.join(" ").trim();
    return { action, args: raw ? JSON.parse(raw) : {}, session };
  }

  let args = {};
  switch (action) {
    case "navigate":
      args = {
        url: requireValue(positional.shift(), "url"),
        ...(options["new-tab"] ? { newTab: true } : {}),
        ...(options["group-title"] ? { group_title: options["group-title"] } : {}),
      };
      break;
    case "find_tab":
      args = {
        url: requireValue(positional.shift(), "url"),
        ...(options.active ? { active: true } : {}),
      };
      break;
    case "click":
      args = { selector: requireValue(positional.shift(), "selector") };
      break;
    case "fill":
      args = {
        selector: requireValue(positional.shift(), "selector"),
        value: requireValue(positional.join(" "), "value"),
      };
      break;
    case "evaluate":
      args = { code: requireValue(positional.join(" "), "code") };
      break;
    case "cdp": {
      const method = requireValue(positional.shift(), "method");
      const raw = positional.join(" ").trim();
      args = { method, params: raw ? JSON.parse(raw) : {} };
      break;
    }
    case "network":
      args = {
        cmd: requireValue(positional.shift(), "cmd"),
        ...(positional[0] ? { filter: positional.join(" ") } : {}),
        ...(options["request-id"] ? { requestId: options["request-id"] } : {}),
      };
      break;
    case "screenshot":
      args = {
        ...(options.format ? { format: options.format } : {}),
        ...(number(options.quality, "quality") != null
          ? { quality: number(options.quality, "quality") }
          : {}),
        ...(options.selector ? { selector: options.selector } : {}),
        ...(options.path ? { path: options.path } : {}),
      };
      break;
    case "save_as_pdf":
      args = {
        ...(options["paper-format"] ? { paper_format: options["paper-format"] } : {}),
        ...(options.landscape ? { landscape: true } : {}),
        ...(number(options.scale, "scale") != null ? { scale: number(options.scale, "scale") } : {}),
        ...(options["print-background"] ? { print_background: true } : {}),
        ...(options.path ? { path: options.path } : {}),
      };
      break;
    case "upload":
      args = {
        selector: requireValue(positional.shift(), "selector"),
        files: positional,
      };
      if (!args.files.length) throw new Error("upload 至少需要一个文件");
      break;
    case "snapshot":
    case "list_tabs":
    case "close_tab":
    case "close_session":
      args = {};
      break;
    default: {
      const raw = positional.join(" ").trim();
      if (!raw) throw new Error(`未知 action: ${action}。如需直接调用，使用 call <action> '<args-json>'。`);
      args = JSON.parse(raw);
    }
  }
  return { action, args, session };
}

function daemonBinary(env = process.env) {
  return env.KIMI_WEBBRIDGE_BIN || join(homedir(), ".kimi-webbridge", "bin", "kimi-webbridge");
}

function startDaemon(env = process.env) {
  const result = spawnSync(daemonBinary(env), ["start"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.error || result.status !== 0) {
    throw new Error(`Kimi WebBridge 守护进程启动失败：${result.stderr || result.error}`);
  }
}

function isConnectionFailure(error) {
  return (
    error instanceof TypeError &&
    (error.cause?.code === "ECONNREFUSED" || error.cause?.code === "ECONNRESET")
  );
}

async function postCommand(command, env = process.env) {
  const response = await fetch(env.KIMI_WEBBRIDGE_URL || DEFAULT_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(command),
    signal: AbortSignal.timeout(120_000),
  });
  const body = await response.text();
  let parsed;
  try {
    parsed = JSON.parse(body);
  } catch {
    throw new Error(`Kimi WebBridge 返回了非 JSON 内容（HTTP ${response.status}）：${body.slice(0, 500)}`);
  }
  if (!response.ok) throw new Error(`Kimi WebBridge HTTP ${response.status}: ${body}`);
  return parsed;
}

export async function sendCommand(command, env = process.env) {
  try {
    return await postCommand(command, env);
  } catch (error) {
    if (!isConnectionFailure(error)) throw error;
    startDaemon(env);
    return postCommand(command, env);
  }
}

export async function main(argv = process.argv.slice(2), env = process.env) {
  if (argv.includes("--help") || argv.includes("-h") || argv.length === 0) {
    console.log(usage());
    return argv.length ? 0 : 2;
  }
  const command = buildCommand(argv, env);
  const response = await sendCommand(command, env);
  console.log(JSON.stringify(response));
  if (response?.ok === false || response?.success === false) return 1;
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then(
    (code) => {
      process.exitCode = code;
    },
    (error) => {
      console.error(
        JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
          help: "https://www.kimi.com/zh-cn/features/webbridge",
        }),
      );
      process.exitCode = 1;
    },
  );
}
