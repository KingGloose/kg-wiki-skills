#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, extname, join } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile, relativePosix, walkFiles } from "../../lib/fs.mjs";
import { VaultNotFoundError, findVault } from "../../lib/vault.mjs";

export const SCOPE_WEIGHT = { wiki: 3, index: 2, raw: 1.2, archive: 0.8 };
export const SCOPES = ["wiki", "index", "raw", "archive"];

export function scopeOf(relativePath) {
  const head = relativePath.split("/")[0] || "";
  if (["wiki", "raw", "archive"].includes(head)) return head;
  if (["index.md", "log.md", "AGENTS.md", "README.md"].includes(relativePath)) return "index";
  return "raw";
}

export function iterMarkdown(vault) {
  const files = [];
  for (const directory of ["wiki", "raw", "archive"]) {
    files.push(...walkFiles(join(vault, directory), (path) => extname(path).toLowerCase() === ".md"));
  }
  const daily = join(vault, "daily");
  if (isDirectory(daily)) {
    for (const path of walkFiles(daily, (path) => extname(path).toLowerCase() === ".md")) {
      if (relativePosix(daily, path).split("/").includes("assets")) files.push(path);
    }
  }
  for (const name of ["index.md", "log.md", "AGENTS.md"]) {
    const path = join(vault, name);
    if (isFile(path)) files.push(path);
  }
  return [...new Set(files)].sort();
}

export function sourceManifest(vault, paths = iterMarkdown(vault)) {
  return Object.fromEntries(
    paths.flatMap((path) => {
      try {
        const stat = statSync(path, { bigint: true });
        return [[relativePosix(vault, path), [stat.mtimeNs.toString(), Number(stat.size)]]];
      } catch {
        return [];
      }
    }),
  );
}

export function indexPath(vault, env = process.env) {
  const digest = createHash("sha256").update(vault).digest("hex").slice(0, 12);
  const cache = env.KG_WIKI_CACHE_DIR || join(homedir(), ".cache", "kg-wiki");
  return join(cache, `index-${digest}.json`);
}

export function buildIndex(vault, file = indexPath(vault), log = console.error) {
  log("[..] 构建索引（只扫 md 文本，跳过图片）");
  const started = performance.now();
  const paths = iterMarkdown(vault);
  const docs = paths.flatMap((path) => {
    try {
      return [{
        path: relativePosix(vault, path),
        scope: scopeOf(relativePosix(vault, path)),
        title: basename(path, extname(path)),
        text: readFileSync(path, "utf8"),
        mtime: statSync(path).mtimeMs / 1000,
      }];
    } catch {
      return [];
    }
  });
  const index = {
    built_at: Date.now() / 1000,
    vault,
    manifest: sourceManifest(vault, paths),
    docs,
  };
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(index), "utf8");
  log(`[ok] 索引 ${docs.length} 个文件，耗时 ${((performance.now() - started) / 1000).toFixed(1)}s → ${basename(file)}`);
  return index;
}

export function loadIndex(vault, file = indexPath(vault), rebuild = false, log = console.error) {
  if (rebuild || !isFile(file)) return buildIndex(vault, file, log);
  let index;
  try {
    index = JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return buildIndex(vault, file, log);
  }
  if (index.vault !== vault) {
    log("[i] 索引属于其他知识库，重建");
    return buildIndex(vault, file, log);
  }
  if (JSON.stringify(index.manifest) !== JSON.stringify(sourceManifest(vault))) {
    log("[i] 检测到文件变更，重建索引");
    return buildIndex(vault, file, log);
  }
  return index;
}

export function tokenizeQuery(query) {
  const parts = query.trim().split(/[\s　,，、;；]+/u).filter(Boolean);
  const tokens = new Set(parts);
  for (const part of parts) {
    if (/^\p{Script=Han}{4,}$/u.test(part)) {
      for (const size of [3, 2]) {
        for (let index = 0; index <= part.length - size; index += 1) {
          tokens.add(part.slice(index, index + size));
        }
      }
    }
  }
  return [...tokens].filter((token) => token.length >= 2);
}

function occurrences(text, value) {
  let count = 0;
  let offset = 0;
  while ((offset = text.indexOf(value, offset)) !== -1) {
    count += 1;
    offset += value.length || 1;
  }
  return count;
}

export function scoreDocument(doc, tokens) {
  const text = doc.text.toLocaleLowerCase();
  const title = doc.title.toLocaleLowerCase();
  const hits = {};
  let score = 0;
  for (const token of tokens) {
    const normalized = token.toLocaleLowerCase();
    const count = occurrences(text, normalized);
    if (count) {
      hits[token] = count;
      score += 1 + Math.min(count, 20) * 0.15;
    }
    if (title.includes(normalized)) score += 4;
  }
  if (!Object.keys(hits).length) return { score: 0, hits: {} };
  score *= 1 + 0.5 * (Object.keys(hits).length / Math.max(tokens.length, 1));
  score *= SCOPE_WEIGHT[doc.scope] ?? 1;
  return { score, hits };
}

export function extractSnippets(text, tokens, context, limit = 3) {
  const lines = text.split(/\r?\n/);
  const lowered = lines.map((line) => line.toLocaleLowerCase());
  const picked = [];
  const used = [];
  for (let index = 0; index < lowered.length; index += 1) {
    if (!tokens.some((token) => lowered[index].includes(token.toLocaleLowerCase()))) continue;
    if (used.some((other) => Math.abs(index - other) <= context)) continue;
    const segment = lines
      .slice(Math.max(0, index - context), Math.min(lines.length, index + context + 1))
      .join("\n")
      .trim();
    if (segment) {
      picked.push(segment);
      used.push(index);
    }
    if (picked.length >= limit) break;
  }
  return picked;
}

export function searchIndex(index, query, { scopes = SCOPES, limit = 8, minScore = 8, context = 1, snippets = 3 } = {}) {
  const tokens = tokenizeQuery(query);
  const allowed = new Set(scopes);
  const ranked = index.docs
    .filter((doc) => allowed.has(doc.scope))
    .map((doc) => ({ doc, ...scoreDocument(doc, tokens) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score);
  return {
    tokens,
    weak: ranked.filter((item) => item.score < minScore),
    results: ranked
      .filter((item) => item.score >= minScore)
      .slice(0, limit)
      .map((item) => ({
        path: item.doc.path,
        scope: item.doc.scope,
        title: item.doc.title,
        score: Math.round(item.score * 100) / 100,
        hits: item.hits,
        snippets: extractSnippets(item.doc.text, tokens, context, snippets),
      })),
  };
}

function parseNumber(value, fallback, name, integer = false) {
  const number = value == null ? fallback : Number(value);
  if (!Number.isFinite(number) || number < 0 || (integer && !Number.isInteger(number))) {
    throw new Error(`${name} 必须是${integer ? "非负整数" : "非负数"}`);
  }
  return number;
}

export function main(argv = process.argv.slice(2)) {
  const { values, positionals } = parseArgs({
    args: argv,
    options: {
      scope: { type: "string" }, limit: { type: "string", default: "8" },
      context: { type: "string", default: "1" }, snippets: { type: "string", default: "3" },
      "min-score": { type: "string", default: "8" }, json: { type: "boolean" },
      rebuild: { type: "boolean" }, stats: { type: "boolean" }, vault: { type: "string" },
      help: { type: "boolean", short: "h" },
    },
    allowPositionals: true,
  });
  if (values.help) {
    console.log("search-vault.mjs <查询> [--scope wiki,raw] [--json] [--rebuild] [--stats] [--vault path]");
    return 0;
  }
  let vault;
  try {
    vault = findVault({ hint: fileURLToPath(import.meta.url), explicit: values.vault });
  } catch (error) {
    if (!(error instanceof VaultNotFoundError)) throw error;
    console.error(`[错误] ${error.message}`);
    return 2;
  }
  const index = loadIndex(vault, indexPath(vault), Boolean(values.rebuild));
  if (values.stats) {
    console.log("# 库构成\n");
    for (const scope of SCOPES) {
      const docs = index.docs.filter((doc) => doc.scope === scope);
      if (docs.length) {
        const chars = docs.reduce((total, doc) => total + doc.text.length, 0);
        console.log(`  ${scope.padEnd(8)} ${String(docs.length).padStart(4)} 个文件  ${String(Math.round(chars / 1024)).padStart(8)} KB  (权重 ${SCOPE_WEIGHT[scope]})`);
      }
    }
    console.log(`\n  合计     ${String(index.docs.length).padStart(4)} 个文件`);
    return 0;
  }
  const query = positionals.join(" ").trim();
  if (!query) {
    console.error("[错误] 需要查询词。用法见 --help");
    return 2;
  }
  const result = searchIndex(index, query, {
    scopes: values.scope ? values.scope.split(",").map((item) => item.trim()) : SCOPES,
    limit: parseNumber(values.limit, 8, "--limit", true),
    context: parseNumber(values.context, 1, "--context", true),
    snippets: parseNumber(values.snippets, 3, "--snippets", true),
    minScore: parseNumber(values["min-score"], 8, "--min-score"),
  });
  if (!result.tokens.length) {
    console.error("[错误] 查询词太短（需至少 2 字符）");
    return 2;
  }
  if (values.json) {
    console.log(JSON.stringify({ query, tokens: result.tokens, results: result.results }, null, 2));
    return 0;
  }
  if (!result.results.length) {
    console.log(`库里没找到「${query}」的相关沉淀。`);
    if (result.weak.length) console.log(`\n（有 ${result.weak.length} 个文件弱命中，低于相关度门槛）`);
    console.log("\n→ 回答时要明确说明「库里没有记录，以下是我的通用知识」。");
    return 0;
  }
  console.log(`# 检索「${query}」\n`);
  for (const item of result.results) {
    console.log(`## ${item.path}\n   相关度 ${item.score} | 命中: ${Object.entries(item.hits).map(([key, value]) => `${key}×${value}`).join(", ")}`);
    item.snippets.forEach((snippet) => console.log(`   ┆ ${snippet.split(/\r?\n/).slice(0, 3).join("\n   ┆ ")}\n   ┆`));
    console.log();
  }
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try { process.exitCode = main(); }
  catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; }
}
