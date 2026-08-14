#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, dirname, extname, join, relative, resolve } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile, isPathInside, relativePosix, walkFiles } from "../../lib/fs.mjs";
import { VaultNotFoundError, findVault } from "../../lib/vault.mjs";

export const CHECKS = ["deadlink", "orphan", "rawlink", "indexsync", "logsync", "empty", "image"];
export const MIN_CHARS = 400;
export const BIG_IMAGE_KB = 500;
export const UNCOMPRESSED_MIN_KB = 100;
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif"]);
const DOCUMENT_EXTENSIONS = new Set([".md", ".canvas"]);
const SKIP_DIRECTORIES = new Set([".git", "node_modules", ".trash", ".obsidian", ".venv", "__pycache__"]);
const LINK_RE = /\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/g;
const IMAGE_REFS = [/!\[\[([^\]|#]+)/g, /!\[[^\]]*\]\(\s*<?([^) >\s]+)/g, /<img[^>]*?\ssrc\s*=\s*["']([^"']+)["']/gi];

export function stripCode(text) {
  const blank = (match) => match.replace(/[^\n]/g, " ");
  return text.replace(/^(```+|~~~+).*?^\1/gms, blank).replace(/`[^`\n]+`/g, blank);
}

function safeRead(path) {
  try { return readFileSync(path, "utf8"); } catch { return ""; }
}

function human(bytes) {
  let value = bytes;
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (value < 1024 || unit === "GB") return `${value.toFixed(1)} ${unit}`;
    value /= 1024;
  }
}

function mentioned(stem, haystack) {
  if (haystack.includes(stem)) return true;
  const lowered = haystack.toLocaleLowerCase();
  const tokens = stem.split(/[\s　/\-—·:：、（）()\[\]]+/u).filter((token) => token.length >= 2);
  if (tokens.some((token) => lowered.includes(token.toLocaleLowerCase()))) return true;
  for (const segment of stem.match(/[\p{Script=Han}]{3,}/gu) || []) {
    for (let size = segment.length; size >= 3; size -= 1) {
      for (let index = 0; index <= segment.length - size; index += 1) {
        if (haystack.includes(segment.slice(index, index + size))) return true;
      }
    }
  }
  return false;
}

function walkSelected(root, extensions) {
  if (!isDirectory(root)) return [];
  const found = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    let entries;
    try { entries = readdirSync(directory, { withFileTypes: true }); } catch { continue; }
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) { if (!SKIP_DIRECTORIES.has(entry.name)) pending.push(path); }
      else if (entry.isFile() && extensions.has(extname(entry.name).toLowerCase())) found.push(path);
    }
  }
  return found.sort();
}

function normalize(value) {
  return value.normalize("NFC");
}

function decodeReference(value) {
  try { return decodeURIComponent(value); } catch { return value; }
}

export function createLinter(vault) {
  const wiki = join(vault, "wiki");
  const raw = join(vault, "raw");
  const index = join(vault, "index.md");
  const log = join(vault, "log.md");
  const wikiPages = () => walkFiles(wiki, (path) => path.endsWith(".md"));
  const pageKey = (path) => relativePosix(wiki, path).replace(/\.md$/i, "");

  const resolveLink = (target, source) => {
    let value = target.trim();
    if (value.includes("#")) {
      value = value.split("#", 1)[0].trim();
      if (!value) return source;
    }
    if (!value.includes("/")) {
      const sameName = wikiPages().find((path) => basename(path, ".md") === value);
      if (sameName) return resolve(sameName);
    }
    const base = dirname(source);
    const candidates = value.includes("/")
      ? [resolve(base, value), resolve(base, `${value}.md`), resolve(vault, value), resolve(vault, `${value}.md`)]
      : [resolve(base, `${value}.md`)];
    return candidates.find(isFile) || null;
  };

  const collectLinks = () => {
    const inbound = {};
    const dead = [];
    for (const page of wikiPages()) {
      let text;
      try { text = readFileSync(page, "utf8"); }
      catch (error) { dead.push({ page: pageKey(page), link: "(读取失败)", reason: String(error) }); continue; }
      for (const match of stripCode(text).matchAll(LINK_RE)) {
        const target = match[1];
        const resolved = resolveLink(target, page);
        if (!resolved) dead.push({ page: pageKey(page), link: target });
        else if (isPathInside(wiki, resolved)) {
          const key = pageKey(resolved);
          if (key !== pageKey(page)) (inbound[key] ??= []).push([pageKey(page), target]);
        }
      }
    }
    return { inbound, dead };
  };

  const checkOrphan = (inbound) => wikiPages().map(pageKey).filter((key) => !inbound[key]?.length).map((page) => ({ page }));
  const checkRawlink = () => {
    if (!isDirectory(raw)) return [];
    const wikiText = wikiPages().map(safeRead).join("\n");
    const logText = safeRead(log);
    return walkFiles(raw, (path) => path.endsWith(".md") && dirname(path) === raw).flatMap((path) => {
      const name = basename(path, ".md"); const file = basename(path);
      return wikiText.includes(name) || wikiText.includes(file) ? [] : [{ raw: file, in_log: logText.includes(name) || logText.includes(file) }];
    });
  };
  const checkIndexsync = () => {
    if (!isFile(index)) return [{ issue: "index.md 不存在" }];
    const text = safeRead(index); const out = [];
    const domains = new Set(wikiPages().map((path) => relative(wiki, path).split(/[\\/]/)[0]).filter((part) => part && !part.endsWith(".md")));
    [...domains].sort().forEach((domain) => { if (!text.includes(`wiki/${domain}`) && !text.includes(domain)) out.push({ domain, issue: "index.md 未提及该领域" }); });
    wikiPages().forEach((path) => { if (!mentioned(basename(path, ".md"), text)) out.push({ page: pageKey(path), issue: "index.md 里找不到相关关键词" }); });
    return out;
  };
  const checkLogsync = () => {
    if (!isFile(log)) return [{ issue: "log.md 不存在" }];
    const text = safeRead(log);
    return wikiPages().flatMap((path) => mentioned(basename(path, ".md"), text) ? [] : [{ page: pageKey(path) }]);
  };
  const checkEmpty = () => wikiPages().flatMap((path) => {
    const chars = safeRead(path).trim().length; return chars < MIN_CHARS ? [{ page: pageKey(path), chars }] : [];
  });

  const checkImage = () => {
    const images = walkSelected(vault, IMAGE_EXTENSIONS);
    const byPath = new Map(images.map((path) => [normalize(resolve(path)).toLocaleLowerCase(), path]));
    const byName = new Map();
    images.forEach((path) => { const key = normalize(basename(path)).toLocaleLowerCase(); byName.set(key, [...(byName.get(key) || []), path]); });
    const referenced = new Set(); const dead = []; const ambiguous = [];
    for (const document of walkSelected(vault, DOCUMENT_EXTENSIONS)) {
      const text = stripCode(safeRead(document));
      for (const pattern of IMAGE_REFS) {
        for (const match of text.matchAll(pattern)) {
          const ref = match[1];
          if (/^[a-z]+:\/\//i.test(ref)) continue;
          const clean = normalize(decodeReference(ref.split("|")[0].split("#")[0])).trim();
          const name = normalize(basename(clean)).toLocaleLowerCase();
          if (!name || !IMAGE_EXTENSIONS.has(extname(name))) continue;
          const exact = [...new Set([resolve(dirname(document), clean), resolve(vault, clean.replace(/^[/\\]+/, ""))].map((path) => byPath.get(normalize(path).toLocaleLowerCase())).filter(Boolean))];
          if (exact.length) { exact.forEach((path) => referenced.add(path)); continue; }
          const matches = byName.get(name) || [];
          if (matches.length === 1) referenced.add(matches[0]);
          else if (matches.length > 1) {
            matches.forEach((path) => referenced.add(path));
            ambiguous.push({ kind: "ambiguous_image", page: relativePosix(vault, document), ref, candidates: matches.map((path) => relativePosix(vault, path)) });
          } else dead.push({ kind: "dead_image", page: relativePosix(vault, document), ref });
        }
      }
    }
    const out = images.filter((path) => !referenced.has(path)).map((path) => ({ kind: "orphan_image", image: relativePosix(vault, path), bytes: statSync(path).size }));
    out.push(...dead, ...ambiguous);
    for (const path of images) {
      const bytes = statSync(path).size; const extension = extname(path).toLowerCase();
      if (bytes > BIG_IMAGE_KB * 1024) out.push({ kind: "big_image", image: relativePosix(vault, path), bytes });
      else if (![".webp", ".svg"].includes(extension) && bytes > UNCOMPRESSED_MIN_KB * 1024) out.push({ kind: "uncompressed", image: relativePosix(vault, path), bytes });
    }
    const hashes = new Map();
    for (const path of images) {
      try { const hash = createHash("md5").update(readFileSync(path)).digest("hex"); hashes.set(hash, [...(hashes.get(hash) || []), path]); } catch {}
    }
    for (const group of hashes.values()) if (group.length > 1) out.push({ kind: "dup_image", image: relativePosix(vault, group[0]), copies: group.length, bytes: statSync(group[0]).size * (group.length - 1) });
    return out;
  };

  const run = (only = CHECKS) => {
    const { inbound, dead } = collectLinks();
    const checks = { deadlink: () => dead, orphan: () => checkOrphan(inbound), rawlink: checkRawlink, indexsync: checkIndexsync, logsync: checkLogsync, empty: checkEmpty, image: checkImage };
    return Object.fromEntries(only.map((name) => [name, checks[name]() ]));
  };
  return { wikiPages, pageKey, resolveLink, collectLinks, checkOrphan, checkRawlink, checkIndexsync, checkLogsync, checkEmpty, checkImage, run };
}

function printReport(vault, linter, todo, result) {
  const total = Object.values(result).reduce((sum, items) => sum + items.length, 0);
  const titles = {
    deadlink: ["死链（指向不存在的页/文件）", "修：改正链接目标，或补上缺失的页"], orphan: ["孤儿页（没有其他页链接到它）", "修：从相关页建双链"],
    rawlink: ["raw 原文未被 wiki 引用", "修：有价值则蒸馏，否则确认只是留档"], indexsync: ["index.md 唤醒条目缺失", "修：补对应领域或关键词"],
    logsync: ["log.md 无摄入记录", "修：补 log 或确认无需追记"], empty: [`内容过短（<${MIN_CHARS} 字符）`, "修：补完或删除占位页"], image: ["图片体积问题", "修：确认后压缩或删除"],
  };
  console.log(`# 库健康检查 · ${basename(vault)}\n\nwiki 页数: ${linter.wikiPages().length}  |  发现问题: ${total}\n`);
  for (const name of todo) {
    const items = result[name] || []; const [title, hint] = titles[name];
    console.log(`## ${items.length ? "⚠️" : "✅"} ${title} — ${items.length}`);
    if (items.length) console.log(`   建议：${hint}`);
    for (const item of items.slice(0, 30)) {
      if (name === "deadlink") console.log(`   · ${item.page} → [[${item.link}]]`);
      else if (name === "rawlink") console.log(`   · ${item.raw} ${item.in_log ? "（log 里有记录）" : "（log 里也没记）"}`);
      else if (name === "empty") console.log(`   · ${item.page} (${item.chars} 字符)`);
      else if (name === "image") console.log(`   · [${item.kind}] ${item.image || item.page || ""}${item.bytes ? ` (${human(item.bytes)})` : ""}${item.ref ? ` → ${item.ref}` : ""}`);
      else console.log(`   · ${item.page || item.domain || item.issue || JSON.stringify(item)}${item.issue && (item.page || item.domain) ? ` — ${item.issue}` : ""}`);
    }
    if (items.length > 30) console.log(`   … 另有 ${items.length - 30} 条`);
    console.log();
  }
  if (!total) console.log("库很健康，没发现问题。");
  return total ? 1 : 0;
}

export function main(argv = process.argv.slice(2)) {
  const { values } = parseArgs({ args: argv, options: { json: { type: "boolean" }, only: { type: "string" }, vault: { type: "string" }, help: { type: "boolean", short: "h" } } });
  if (values.help) { console.log(`lint-vault.mjs [--json] [--only ${CHECKS.join(",")}] [--vault path]`); return 0; }
  let vault;
  try { vault = findVault({ hint: fileURLToPath(import.meta.url), explicit: values.vault }); }
  catch (error) { if (!(error instanceof VaultNotFoundError)) throw error; console.error(`[错误] ${error.message}`); return 2; }
  if (!isDirectory(join(vault, "wiki"))) { console.error(`[错误] 找不到 wiki 目录: ${join(vault, "wiki")}`); return 2; }
  const todo = values.only ? values.only.split(",").map((item) => item.trim()).filter((item) => CHECKS.includes(item)) : CHECKS;
  if (!todo.length) { console.error(`[错误] --only 无有效检查项。可选: ${CHECKS.join(",")}`); return 2; }
  const linter = createLinter(vault); const result = linter.run(todo);
  const total = Object.values(result).reduce((sum, items) => sum + items.length, 0);
  if (values.json) { console.log(JSON.stringify({ vault, wiki_pages: linter.wikiPages().length, total_findings: total, findings: result }, null, 2)); return total ? 1 : 0; }
  return printReport(vault, linter, todo, result);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; }
}
