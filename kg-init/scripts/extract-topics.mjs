#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { basename, relative, resolve, sep } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { isDirectory, walkFiles } from "../../lib/fs.mjs";
import { expandHome } from "../../lib/vault.mjs";

const SKIP = new Set([".git", ".obsidian", "node_modules", ".venv", "__pycache__", ".trash"]);
const NOISE = new Set(["总结", "其他", "小结", "补充", "note", "notes", "todo", "待办", "参考", "参考资料", "附录", "前言", "简介", "介绍", "概述", "目录"]);

export function isNoise(title) {
  const value = title.trim().toLocaleLowerCase().replace(/[：:]$/, "");
  return NOISE.has(value) || /^[\d\s.、\-—_()（）]+$/.test(value);
}

export function extractTopics(root, { level = 2, minLength = 2 } = {}) {
  const grouped = {};
  for (const path of walkFiles(root, (file) => file.endsWith(".md"))) {
    const parts = relative(root, path).split(sep); if (parts.some((part) => part.startsWith(".") || SKIP.has(part))) continue;
    let text; try { text = readFileSync(path, "utf8"); } catch { continue; }
    const headings = [...text.matchAll(/^(#{1,6})\s+(.+?)\s*$/gm)].flatMap((match) => {
      const depth = match[1].length; const title = match[2].replace(/[*_`~]/g, "").replace(/^[\d.、]+\s*/, "").trim();
      return depth <= level && title.length >= minLength && !isNoise(title) ? [{ level: depth, title }] : [];
    });
    if (!headings.length) continue;
    const rel = parts.join("/"); const domain = parts.length > 1 ? parts[0] : "(根目录)";
    (grouped[domain] ??= []).push({ file: rel, stem: basename(path, ".md"), headings, chars: text.length });
  }
  return grouped;
}

function printTopics(root, data) {
  const files = Object.values(data).reduce((sum, items) => sum + items.length, 0); const headings = Object.values(data).flat().reduce((sum, item) => sum + item.headings.length, 0);
  console.log(`# index.md 唤醒条目草稿\n\n> 来源: ${root}\n> 扫描 ${files} 个文件，抽出 ${headings} 个标题（已过滤噪声标题）\n>\n> **这是草稿。** AI 需归并同类、删低价值项，再压缩成可扫描关键词。\n`);
  for (const [domain, items] of Object.entries(data).sort(([a], [b]) => a.localeCompare(b))) {
    console.log(`\n## ${domain}\n`);
    for (const item of items.toSorted((a, b) => b.chars - a.chars)) {
      console.log(`- **${item.stem}** (\`${item.file}\`)`);
      const sections = item.headings.filter((heading) => heading.level > 1).map((heading) => heading.title);
      let line = ""; const lines = [];
      for (const section of sections) { if (line.length + section.length > 100) { lines.push(line.replace(/、$/, "")); line = ""; } line += `${section}、`; }
      if (line) lines.push(line.replace(/、$/, "")); lines.slice(0, 6).forEach((value) => console.log(`    ${value}`));
    }
  }
}

export function main(argv = process.argv.slice(2)) {
  const { values, positionals } = parseArgs({ args: argv, options: { level: { type: "string", default: "2" }, "min-len": { type: "string", default: "2" }, json: { type: "boolean" }, help: { type: "boolean", short: "h" } }, allowPositionals: true });
  if (values.help) { console.log("extract-topics.mjs <目录> [--level N] [--min-len N] [--json]"); return 0; }
  const root = resolve(expandHome(positionals[0] || "")); if (!positionals[0] || !isDirectory(root)) { console.error(`[错误] 目录不存在: ${root}`); return 1; }
  const level = Number(values.level); const minLength = Number(values["min-len"]); if (![level, minLength].every((value) => Number.isInteger(value) && value >= 1)) throw new Error("--level/--min-len 必须是正整数");
  const data = extractTopics(root, { level, minLength }); if (!Object.keys(data).length) { console.log(`[i] ${root} 下没找到含标题的 md 文件`); return 0; }
  if (values.json) console.log(JSON.stringify(data, null, 2)); else printTopics(root, data); return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
