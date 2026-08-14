#!/usr/bin/env node
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, extname, relative, resolve, sep } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile } from "../../lib/fs.mjs";
import { expandHome } from "../../lib/vault.mjs";

const NOTE_EXTENSIONS = new Set([".md", ".markdown", ".txt"]);
const DOCUMENT_EXTENSIONS = new Set([".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx", ".mht", ".mhtml"]);
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tiff"]);
const SKIP_DIRECTORIES = new Set([".git", ".obsidian", "node_modules", ".venv", "__pycache__", ".trash", ".DS_Store", "archive"]);

function human(bytes) {
  let value = bytes;
  for (const unit of ["B", "KB", "MB", "GB", "TB"]) {
    if (value < 1024 || unit === "TB") return unit === "B" ? `${value.toFixed(0)}${unit}` : `${value.toFixed(1)}${unit}`;
    value /= 1024;
  }
}

function walk(root) {
  const files = []; const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    let entries; try { entries = readdirSync(directory, { withFileTypes: true }); } catch { continue; }
    for (const entry of entries) {
      if (entry.name.startsWith(".")) continue;
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) { if (!SKIP_DIRECTORIES.has(entry.name)) pending.push(path); }
      else if (entry.isFile()) files.push(path);
    }
  }
  return files;
}

export function scanNotes(root) {
  const notes = []; const docs = []; const images = []; const others = []; const byDomain = new Map();
  const referenced = new Set(); const imageNames = new Set(); let wikiLinks = 0; let chars = 0;
  for (const path of walk(root)) {
    let size; try { size = statSync(path).size; } catch { continue; }
    const rel = relative(root, path).split(sep).join("/"); const extension = extname(path).toLowerCase(); const domain = rel.includes("/") ? rel.split("/")[0] : "(根目录)";
    if (NOTE_EXTENSIONS.has(extension)) {
      notes.push([rel, size]); byDomain.set(domain, (byDomain.get(domain) || 0) + 1);
      try {
        const text = readFileSync(path, "utf8"); chars += text.length; wikiLinks += [...text.matchAll(/\[\[([^\]|]+)/g)].length;
        for (const match of text.matchAll(/!\[[^\]]*\]\(([^)]+)\)|!\[\[([^\]]+)\]\]/g)) {
          const target = (match[1] || match[2] || "").split("|")[0].trim(); if (target) referenced.add(basename(target));
        }
      } catch {}
    } else if (DOCUMENT_EXTENSIONS.has(extension)) docs.push([rel, size]);
    else if (IMAGE_EXTENSIONS.has(extension)) { images.push([rel, size]); imageNames.add(basename(path)); }
    else others.push([rel, size]);
  }
  const orphanImages = new Set([...imageNames].filter((name) => !referenced.has(name)));
  return {
    root,
    notes: { count: notes.length, size: notes.reduce((sum, [, size]) => sum + size, 0), chars, biggest: notes.toSorted((a, b) => b[1] - a[1]).slice(0, 50) },
    docs: { count: docs.length, size: docs.reduce((sum, [, size]) => sum + size, 0), list: docs.toSorted((a, b) => b[1] - a[1]).slice(0, 50) },
    images: { count: images.length, size: images.reduce((sum, [, size]) => sum + size, 0), orphan_count: orphanImages.size, orphan_size: images.filter(([rel]) => orphanImages.has(basename(rel))).reduce((sum, [, size]) => sum + size, 0) },
    others: { count: others.length, size: others.reduce((sum, [, size]) => sum + size, 0) },
    by_domain: Object.fromEntries([...byDomain].sort((a, b) => b[1] - a[1])), wikiLinks,
    existing_structure: Object.fromEntries(["AGENTS.md", "index.md", "log.md"].map((name) => [name, isFile(resolve(root, name))]).concat(["wiki", "raw", "archive"].map((name) => [`${name}/`, isDirectory(resolve(root, name))]))),
  };
}

export function reportNotes(data, top = 15) {
  const note = data.notes; const doc = data.docs; const image = data.images; const total = note.size + doc.size + image.size + data.others.size;
  console.log(`# 笔记体检报告\n\n目录: ${data.root}\n\n## 家底\n`);
  console.log(`  笔记(md/txt)  ${String(note.count).padStart(5)} 个   ${human(note.size).padStart(8)}   约 ${Math.floor(note.chars / 1000)}k 字`);
  console.log(`  文档(doc/pdf) ${String(doc.count).padStart(5)} 个   ${human(doc.size).padStart(8)}`);
  console.log(`  图片          ${String(image.count).padStart(5)} 个   ${human(image.size).padStart(8)}   其中 ${image.orphan_count} 张未被引用(${human(image.orphan_size)})`);
  console.log(`  其他          ${String(data.others.count).padStart(5)} 个   ${human(data.others.size).padStart(8)}\n  ─────────────────────────────\n  合计                      ${human(total).padStart(8)}`);
  console.log(`\n  现有双链(\`[[...]]\`): ${data.wikiLinks} 处${data.wikiLinks > 10 ? "  ← 已有关联意识" : "  ← 基本是孤立笔记"}\n\n## 领域分布（按笔记数）\n`);
  const max = Math.max(...Object.values(data.by_domain), 1);
  Object.entries(data.by_domain).slice(0, top).forEach(([name, count]) => console.log(`  ${name.slice(0, 28).padEnd(30)} ${"█".repeat(Math.min(Math.floor(count / max * 30), 30))} ${count}`));
  console.log("\n## 最大的笔记\n"); note.biggest.slice(0, top).forEach(([name, size]) => console.log(`  ${human(size).padStart(8)}  ${name}`));
  if (doc.count) { console.log("\n## 非 md 文档（需要转换才能被 AI 读）\n"); doc.list.slice(0, top).forEach(([name, size]) => console.log(`  ${human(size).padStart(8)}  ${name}`)); }
  console.log("\n## 已有的 LLM Wiki 结构\n"); Object.entries(data.existing_structure).forEach(([name, exists]) => console.log(`  ${exists ? "✅" : "⬜"} ${name}`));
  console.log("\n---\n\n## 改造建议\n");
  if (data.existing_structure["AGENTS.md"] && data.existing_structure["wiki/"]) console.log("  已经是 LLM Wiki 结构了；按上方清单补齐即可。");
  else console.log(`  建议走「整体归档 + 向前新建」：原样归档 ${note.count} 个笔记和 ${image.count} 张图，新建 wiki/raw/assets，再按需升级旧笔记。`);
}

export function main(argv = process.argv.slice(2)) {
  const { values, positionals } = parseArgs({ args: argv, options: { json: { type: "boolean" }, top: { type: "string", default: "15" }, help: { type: "boolean", short: "h" } }, allowPositionals: true });
  if (values.help) { console.log("analyze-notes.mjs <目录> [--json] [--top N]"); return 0; }
  const root = resolve(expandHome(positionals[0] || "")); if (!positionals[0] || !isDirectory(root)) { console.error(`[错误] 目录不存在: ${root}`); return 1; }
  const top = Number(values.top); if (!Number.isInteger(top) || top < 1) throw new Error("--top 必须是正整数");
  const data = scanNotes(root); if (values.json) console.log(JSON.stringify(data, null, 2)); else reportNotes(data, top); return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
