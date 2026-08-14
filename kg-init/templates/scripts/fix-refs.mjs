#!/usr/bin/env node
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MAP_FILE = process.env.KG_COMPRESS_MAP || join(REPOSITORY, ".compress-map.tsv");
const TEXT_EXTENSIONS = new Set([".md", ".canvas"]);
const SKIP_DIRECTORIES = new Set([".git", "node_modules", ".trash", ".obsidian", ".venv"]);

function normalize(value) { return value.normalize("NFC"); }
function decode(value) { try { return decodeURIComponent(value); } catch { return value; } }

export function loadMap(file = MAP_FILE) {
  let text; try { text = readFileSync(file, "utf8"); } catch { throw new Error(`找不到映射表 ${file}，先跑 scripts/compress-images.sh`); }
  const byBase = new Map();
  for (const line of text.split(/\r?\n/)) {
    if (!line.includes("\t")) continue; const [oldPath, newPath] = line.split("\t", 2); const key = normalize(basename(oldPath)).toLocaleLowerCase();
    byBase.set(key, [...(byBase.get(key) || []), [normalize(oldPath), normalize(newPath)]]);
  }
  return byBase;
}

export function resolveReference(reference, documentDirectory, byBase, repository = REPOSITORY) {
  const decoded = normalize(decode(reference)); const candidates = byBase.get(basename(decoded).toLocaleLowerCase()); if (!candidates?.length) return null;
  let selected = candidates[0];
  if (candidates.length > 1) {
    const documentRelative = relative(repository, documentDirectory).split(sep).join("/"); let bestScore = -1;
    for (const candidate of candidates) {
      const [oldPath] = candidate; let score = 0; const clean = decoded.replace(/^\.\//, ""); if (clean && oldPath.endsWith(clean)) score += 10; if (dirname(oldPath) === documentRelative) score += 5;
      if (score > bestScore) { selected = candidate; bestScore = score; }
    }
  }
  const [oldPath, newPath] = selected; const oldName = basename(oldPath); const newName = basename(newPath); if (oldName === newName) return null;
  const encodedOld = encodeURIComponent(oldName).replace(/%2F/gi, "/"); let index = reference.lastIndexOf(encodedOld);
  if (index >= 0) return reference.slice(0, index) + encodeURIComponent(newName).replace(/%2F/gi, "/") + reference.slice(index + encodedOld.length);
  index = reference.lastIndexOf(oldName); if (index >= 0) return reference.slice(0, index) + newName + reference.slice(index + oldName.length);
  const prefix = dirname(reference); return prefix === "." ? newName : `${prefix}/${newName}`;
}

const PATTERNS = [
  /(!\[\[)([^\]|#]+)([^\]]*)(\]\])/g,
  /(!\[[^\]]*\]\(\s*<)([^>]+)(>\s*(?:"[^"]*"|'[^']*')?\s*\))/g,
  /(!\[[^\]]*\]\(\s*)([^)< >\s]+)(\s*(?:"[^"]*"|'[^']*')?\s*\))/g,
  /(<img[^>]*?\ssrc\s*=\s*["'])([^"']+)(["'])/gi,
];

export function rewriteText(text, documentDirectory, byBase, repository = REPOSITORY) {
  let count = 0; let rewritten = text;
  for (const pattern of PATTERNS) {
    rewritten = rewritten.replace(pattern, (whole, before, reference, ...rest) => {
      if (/^[a-z]+:\/\//i.test(reference)) return whole; const replacement = resolveReference(reference, documentDirectory, byBase, repository); if (!replacement || replacement === reference) return whole;
      count += 1; const suffix = rest.slice(0, -2).join(""); return before + replacement + suffix;
    });
  }
  return { text: rewritten, count };
}

function walk(root) {
  const files = []; const pending = [root];
  while (pending.length) {
    const directory = pending.pop(); let entries; try { entries = readdirSync(directory, { withFileTypes: true }); } catch { continue; }
    for (const entry of entries) { const path = join(directory, entry.name); if (entry.isDirectory()) { if (!SKIP_DIRECTORIES.has(entry.name)) pending.push(path); } else if (entry.isFile() && TEXT_EXTENSIONS.has(extname(entry.name).toLowerCase())) files.push(path); }
  }
  return files.sort();
}

export function main(argv = process.argv.slice(2)) {
  const files0 = argv.includes("--files0"); const dryRun = files0 || argv.includes("--dry-run"); const byBase = loadMap(); const affected = []; let references = 0;
  for (const path of walk(REPOSITORY)) {
    let original; try { original = readFileSync(path, "utf8"); } catch { continue; }
    const result = rewriteText(original, dirname(path), byBase); if (!result.count) continue; affected.push(relative(REPOSITORY, path).split(sep).join("/")); references += result.count; if (!dryRun) writeFileSync(path, result.text, "utf8");
  }
  if (files0) { if (affected.length) process.stdout.write(Buffer.from(`${affected.join("\0")}\0`)); return 0; }
  console.log(`映射表 ${[...byBase.values()].flat().length} 条`); affected.forEach((path) => console.log(`  ${path}`)); console.log(`\n${dryRun ? "[dry-run] " : ""}改写 ${references} 处引用，涉及 ${affected.length} 个文件`); return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
