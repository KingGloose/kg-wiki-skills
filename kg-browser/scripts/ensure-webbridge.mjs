#!/usr/bin/env node
// 确保 Kimi WebBridge 服务端可用（Windows 侧）。
//
// 背景：大部分 AI 跑在 WSL，Chrome/扩展在 Windows。WebBridge 服务端
// （kimi-webbridge mcp，监听 10086）由 Windows 侧进程提供。本脚本在
// WSL 侧检测该服务是否可达；不可达时用 WSL interop 拉起 Windows 侧
// 服务端（隐藏窗口），并轮询等待就绪。
//
// 用法:
//   node ensure-webbridge.mjs [waitMs] [--json]
//   waitMs: 等待就绪的最长时间，默认 20000
//
// 退出码: 0 = 服务可用（本来就在跑或已拉起），1 = 拉起失败

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const PORT = 10086;

function windowsGatewayIp() {
  try {
    const route = readRoute();
    for (const line of route.split("\n").slice(1)) {
      const parts = line.trim().split(/\s+/);
      if (parts[0] && parts[1] === "00000000" && parts[2]) {
        const gw = parts[2];
        return [3, 2, 1, 0].map((i) => parseInt(gw.slice(i * 2, i * 2 + 2), 16)).join(".");
      }
    }
  } catch {}
  return null;
}

function readRoute() {
  try {
    return readFileSync("/proc/net/route", "utf8");
  } catch {
    return "";
  }
}

function probe(host, port, timeoutMs = 4000) {
  // 完整就绪 = 服务端在跑 + Chrome 扩展已连接(能返回 tool_result.data)。
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    let ws;
    try {
      ws = new WebSocket(`ws://${host}:${port}/ws`);
    } catch {
      return done(false);
    }
    const timer = setTimeout(() => {
      try {
        ws.close();
      } catch {}
      done(false);
    }, timeoutMs);
    ws.onopen = () => {
      try {
        ws.send(
          JSON.stringify({
            type: "tool_call",
            requestId: crypto.randomUUID(),
            payload: { name: "list_tabs", args: {} },
          })
        );
      } catch {}
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "tool_result") {
          clearTimeout(timer);
          try {
            ws.close();
          } catch {}
          // 扩展就绪时 payload.data 存在；未就绪时只有 payload.error
          done(Boolean(msg.payload && msg.payload.data !== undefined && msg.payload.data !== null));
        }
      } catch {}
    };
    ws.onerror = () => {
      clearTimeout(timer);
      done(false);
    };
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function startOnWindows() {
  // 用 WSL interop 在 Windows 侧后台启动（隐藏窗口，日志落 %USERPROFILE%\kimi-webbridge.log）
  const ps =
    "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npx -y kimi-webbridge@0.1.3 mcp > %USERPROFILE%\\kimi-webbridge.log 2>&1' -WindowStyle Hidden";
  const r = spawnSync("powershell.exe", ["-NoProfile", "-Command", ps], {
    encoding: "utf8",
    timeout: 20_000,
  });
  return r.status === 0;
}

async function main() {
  const json = process.argv.includes("--json");
  const waitArg = process.argv.find((a) => /^\d+$/.test(a));
  const waitMs = waitArg ? parseInt(waitArg, 10) : 20_000;

  const host = windowsGatewayIp();
  if (!host) {
    if (json) console.log(JSON.stringify({ ok: false, error: "无法确定 Windows 网关" }));
    else console.error("无法确定 Windows 网关（非 WSL2？）");
    return 1;
  }

  if (await probe(host, PORT)) {
    if (json) console.log(JSON.stringify({ ok: true, running: true, host }));
    else console.log(`已就绪：${host}:${PORT}（本来就在跑）`);
    return 0;
  }

  if (json) console.log(JSON.stringify({ ok: false, starting: true, host }));
  else console.log(`服务未运行，正在拉起 Windows 侧服务端（${host}:${PORT}）...`);

  if (!startOnWindows()) {
    if (json) console.log(JSON.stringify({ ok: false, error: "Windows 侧启动命令执行失败" }));
    else console.error("Windows 侧启动命令执行失败");
    return 1;
  }

  // 轮询等待就绪
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    await sleep(1000);
    if (await probe(host, PORT)) {
      if (json) console.log(JSON.stringify({ ok: true, running: true, host, started: true }));
      else console.log(`已拉起并就绪：${host}:${PORT}`);
      return 0;
    }
  }

  if (json) console.log(JSON.stringify({ ok: false, error: `等待 ${waitMs}ms 仍未就绪` }));
  else console.error(`等待 ${waitMs}ms 后服务仍未就绪`);
  return 1;
}

// 允许被 require 复用
export async function ensureWebbridge(waitMs = 20_000) {
  return mainWith(waitMs);
}

async function mainWith(waitMs) {
  const host = windowsGatewayIp();
  if (!host) return { ok: false, error: "无法确定 Windows 网关" };
  if (await probe(host, PORT)) return { ok: true, running: true, host };
  startOnWindows();
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    await sleep(1000);
    if (await probe(host, PORT)) return { ok: true, running: true, host, started: true };
  }
  return { ok: false, error: "拉起后等待超时" };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then((code) => {
    process.exitCode = code;
  });
}
