#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join, relative, resolve, sep } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile, isPathInside, readJson, relativePosix, walkFiles, writeJsonAtomic } from "../../lib/fs.mjs";
import { VaultNotFoundError, findVault } from "../../lib/vault.mjs";

export const STRATEGIES = ["stale", "recent", "random", "orphanish"];
const JUDGMENT_MARKERS = ["⭐", "我的判断", "我认为", "我倾向", "我原以为", "个人判断", "对照观察", "自己的判断", "我的看法", "踩坑", "教训", "现在回看"];

export function reviewLogPath(vault, env = process.env) {
  const digest = createHash("sha256").update(resolve(vault)).digest("hex").slice(0, 12);
  const root = env.KG_AGENT_CONFIG_DIR?.trim() || join(homedir(), ".kg-agent-config");
  return join(root, "state", `review-${digest}.json`);
}

export function pages(vault, domain) {
  const wiki = join(vault, "wiki");
  if (!isDirectory(wiki)) return [];
  return walkFiles(wiki, (path) => path.endsWith(".md")).filter((path) => {
    if (!domain) return true;
    const [head] = relative(wiki, path).split(sep);
    return head.toLocaleLowerCase() === domain.toLocaleLowerCase();
  });
}

export function linkCount(path, allText) {
  const stem = basename(path, ".md");
  return allText.split(`[[${stem}]]`).length - 1 + (allText.split(`/${stem}]]`).length - 1);
}

export function daysSince(timestamp, now = Date.now() / 1000) {
  return timestamp ? (now - timestamp) / 86_400 : null;
}

export function hasOwnJudgment(text) {
  return JUDGMENT_MARKERS.some((marker) => text.includes(marker));
}

export function summarize(path) {
  const text = readFileSync(path, "utf8");
  const lines = text.split(/\r?\n/);
  let gist = "";
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.includes("一句话主旨") || (line.includes("一句话") && line.startsWith("#"))) {
      gist = lines.slice(index + 1, index + 8).map((item) => item.trim()).find((item) => item && !/^[#>\-|]/.test(item)) || "";
      break;
    }
  }
  if (!gist) gist = lines.slice(1, 25).map((item) => item.trim()).find((item) => item.startsWith(">") && item.length > 12)?.replace(/^>\s*/, "") || "";
  const sections = lines.filter((line) => /^##\s/.test(line)).map((line) => line.replace(/^#+\s*[\d.]*\s*/, "").trim()).slice(0, 12);
  return { chars: text.length, gist: gist.slice(0, 200), sections, has_own_judgment: hasOwnJudgment(text) };
}

function shuffle(items) {
  for (let index = items.length - 1; index > 0; index -= 1) {
    const other = Math.floor(Math.random() * (index + 1));
    [items[index], items[other]] = [items[other], items[index]];
  }
}

export function buildReviewItems(vault, reviews, domain) {
  const wiki = join(vault, "wiki");
  const allText = pages(vault).flatMap((path) => {
    try { return [readFileSync(path, "utf8")]; } catch { return []; }
  }).join("\n");
  return pages(vault, domain).flatMap((path) => {
    try {
      const rel = relativePosix(vault, path);
      const record = reviews[rel] || {};
      const parts = relative(wiki, path).split(sep);
      return [{ path: rel, title: basename(path, ".md"), domain: parts.length > 1 ? parts[0] : "", mtime: statSync(path).mtimeMs / 1000, review_count: record.count || 0, last_review: record.last ?? null, inbound_links: linkCount(path, allText) }];
    } catch { return []; }
  });
}

function parseNonnegativeInteger(value, name) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0) throw new Error(`${name} 必须是非负整数`);
  return number;
}

export function main(argv = process.argv.slice(2)) {
  const { values } = parseArgs({
    args: argv,
    options: {
      count: { type: "string", default: "3" }, strategy: { type: "string", default: "stale" },
      domain: { type: "string" }, mark: { type: "string" }, status: { type: "boolean" },
      json: { type: "boolean" }, vault: { type: "string" }, help: { type: "boolean", short: "h" },
    },
  });
  if (values.help) { console.log("pick-review.mjs [--count N] [--strategy stale|recent|random|orphanish] [--domain name] [--mark wiki/...] [--status] [--vault path]"); return 0; }
  if (!STRATEGIES.includes(values.strategy)) throw new Error(`未知策略: ${values.strategy}`);
  const count = parseNonnegativeInteger(values.count, "--count");
  let vault;
  try { vault = findVault({ hint: fileURLToPath(import.meta.url), explicit: values.vault }); }
  catch (error) { if (!(error instanceof VaultNotFoundError)) throw error; console.error(`[错误] ${error.message}`); return 2; }
  const wiki = join(vault, "wiki");
  const logFile = reviewLogPath(vault);
  const log = readJson(logFile, { reviews: {} });
  if (!log.reviews || typeof log.reviews !== "object" || Array.isArray(log.reviews)) log.reviews = {};
  if (values.mark) {
    const target = resolve(vault, values.mark);
    if (!isFile(target) || !isPathInside(wiki, target)) { console.error(`[错误] --mark 必须是当前知识库 wiki/ 下已存在的文件: ${values.mark}`); return 1; }
    const key = relativePosix(vault, target);
    const record = log.reviews[key] ?? { count: 0, last: null };
    record.count += 1; record.last = Date.now() / 1000; log.reviews[key] = record; writeJsonAtomic(logFile, log);
    console.log(`✅ 已标记回顾: ${key}（累计 ${record.count} 次）`); return 0;
  }
  const items = buildReviewItems(vault, log.reviews, values.domain);
  if (!items.length) { console.error(`[错误] 没找到 wiki 页${values.domain ? `（领域: ${values.domain}）` : ""}`); return 1; }
  if (values.status) {
    console.log("# 回顾状态\n");
    items.sort((left, right) => left.review_count - right.review_count || right.mtime - left.mtime);
    items.forEach((item) => { const days = daysSince(item.last_review); console.log(`  ${String(item.review_count).padStart(2)} 次 | ${(days == null ? "从未回顾" : `${days.toFixed(0)} 天前`).padStart(10)} | 链入 ${String(item.inbound_links).padStart(2)} | ${item.path}`); });
    console.log(`\n  共 ${items.length} 页，其中 ${items.filter((item) => item.review_count === 0).length} 页从未回顾`); return 0;
  }
  if (values.strategy === "stale") items.sort((left, right) => left.review_count - right.review_count || (left.last_review || 0) - (right.last_review || 0));
  else if (values.strategy === "recent") items.sort((left, right) => right.mtime - left.mtime);
  else if (values.strategy === "orphanish") items.sort((left, right) => left.inbound_links - right.inbound_links || left.review_count - right.review_count);
  else shuffle(items);
  const picked = items.slice(0, count).map((item) => ({ ...item, ...summarize(join(vault, item.path)) }));
  if (values.json) { console.log(JSON.stringify({ strategy: values.strategy, picked }, null, 2)); return 0; }
  console.log(`# 回顾 ${picked.length} 页（策略: ${values.strategy}）\n`);
  picked.forEach((item, index) => {
    const days = daysSince(item.last_review);
    console.log(`## ${index + 1}. ${item.title}\n   \`${item.path}\` | ${item.chars} 字符 | 链入 ${item.inbound_links} | 回顾 ${item.review_count} 次 | ${days == null ? "**从未回顾**" : `${days.toFixed(0)} 天前回顾过`}`);
    if (item.gist) console.log(`   主旨: ${item.gist}`);
    if (item.sections.length) console.log(`   小节: ${item.sections.slice(0, 6).join(" / ")}`);
    if (item.has_own_judgment) console.log("   ⭐ 含个人判断——回顾时重点确认这部分还认同吗");
    console.log();
  });
  console.log("---\n回顾方式（给 AI 的提示）:\n  1. 先只看标题和主旨，让用户先回想。\n  2. 含个人判断的页，确认现在是否仍认同。\n  3. 回顾完用 --mark <路径> 记一笔。");
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; }
}
