#!/usr/bin/env node
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";

const DEFAULT_BASE = "https://aihot.virxact.com/api/v1";
const COMMANDS = new Set(["today", "week", "hot", "daily", "search", "category", "all"]);

export async function fetchAihot(
  path,
  { base = process.env.AIHOT_BASE || DEFAULT_BASE, fetchImpl = fetch } = {},
) {
  let response;
  try {
    response = await fetchImpl(`${base}${path}`, {
      headers: { accept: "application/json", "user-agent": "kg-wiki-agent/1.0" },
      signal: AbortSignal.timeout(20_000),
    });
  } catch (error) {
    throw new Error(`AIHOT 请求失败：${error instanceof Error ? error.message : String(error)}`);
  }
  if (!response.ok) throw new Error(`AIHOT 请求失败：HTTP ${response.status}`);
  try {
    return await response.json();
  } catch (error) {
    throw new Error(`AIHOT 返回的不是合法 JSON：${error instanceof Error ? error.message : String(error)}`);
  }
}

export function formatItems(data, limit = 8) {
  const items = data.items ?? [];
  if (!items.length) return "（无数据）";
  const lines = [`AIHOT · 共 ${items.length} 条`];
  items.slice(0, limit).forEach((item, index) => {
    const title = item.title || item.originalTitle || "";
    const link = item.links?.aihot || item.url || "";
    lines.push(`${String(index + 1).padStart(2)}. ${title}`);
    if (link) lines.push(`    ${link}`);
    if (item.summary) lines.push(`    ${item.summary.slice(0, 120)}`);
  });
  return lines.join("\n");
}

export function formatHot(data) {
  const items = data.topics ?? data.items ?? [];
  if (!items.length) return "（无数据）";
  const lines = [`AIHOT 当前最热 · 共 ${items.length} 条`];
  items.slice(0, 10).forEach((item, index) => {
    lines.push(`${String(index + 1).padStart(2)}. ${item.title || item.topic || ""}`);
    const link = item.links?.aihot || item.url || "";
    if (link) lines.push(`    ${link}`);
  });
  return lines.join("\n");
}

export function formatDaily(data) {
  const daily = data.daily ?? data;
  return `AIHOT 日报 · ${daily.title || "AI 日报"}\n\n${String(daily.content || daily.body || "").slice(0, 3000)}`;
}

export async function main(argv = process.argv.slice(2)) {
  const { values, positionals } = parseArgs({
    args: argv,
    options: { limit: { type: "string", default: "8" }, help: { type: "boolean", short: "h" } },
    allowPositionals: true,
  });
  if (values.help) {
    console.log("aihot.mjs [today|week|hot|daily|search|category|all] [关键词] [--limit N]");
    return 0;
  }
  const command = positionals[0] ?? "today";
  if (!COMMANDS.has(command)) throw new Error(`未知命令: ${command}`);
  const limit = Number(values.limit);
  if (!Number.isInteger(limit) || limit < 1) throw new Error("--limit 必须是正整数");
  const arg = positionals[1] ?? "";
  if (command === "hot") console.log(formatHot(await fetchAihot("/hot-topics")));
  else if (command === "daily") console.log(formatDaily(await fetchAihot("/dailies/latest")));
  else {
    const path = {
      today: "/items?mode=selected&window=24h",
      week: "/items?mode=selected&window=7d&limit=10",
      search: `/items?mode=selected&q=${encodeURIComponent(arg)}&window=7d&limit=10`,
      category: `/items?mode=selected&category=${encodeURIComponent(arg || "model")}&window=24h`,
      all: `/items?mode=all&window=24h&limit=${limit}`,
    }[command];
    console.log(formatItems(await fetchAihot(path), limit));
  }
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then(
    (code) => { process.exitCode = code; },
    (error) => {
      console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`);
      process.exitCode = 1;
    },
  );
}
