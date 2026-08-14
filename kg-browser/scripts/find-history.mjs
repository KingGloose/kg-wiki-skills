#!/usr/bin/env node
import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import { homedir, platform, tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

const CHROME_TO_UNIX_MICROSECONDS = 11_644_473_600_000_000n;
const NOISE_PATTERNS = [
  "/search",
  "?q=",
  "&q=",
  "/signin",
  "/login",
  "/logout",
  "/auth",
  "google.com/search",
  "bing.com/search",
  "baidu.com/s?",
  "/tardis/",
  "/landing/",
];

function isDirectory(path) {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function isFile(path) {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

export function isWsl() {
  try {
    return readFileSync("/proc/version", "utf8").toLowerCase().includes("microsoft");
  } catch {
    return false;
  }
}

function wslWindowsChromeHomes() {
  const users = "/mnt/c/Users";
  if (!isDirectory(users)) return [];
  const ignored = new Set(["Public", "Default", "Default User", "All Users"]);
  try {
    return readdirSync(users, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !ignored.has(entry.name))
      .map((entry) => join(users, entry.name, "AppData/Local/Google/Chrome/User Data"))
      .filter(isDirectory);
  } catch {
    return [];
  }
}

export function defaultChromeHomes(env = process.env) {
  if (platform() === "darwin") {
    return [join(homedir(), "Library/Application Support/Google/Chrome")];
  }
  if (platform() === "win32") {
    const base = env.LOCALAPPDATA || join(homedir(), "AppData/Local");
    return [join(base, "Google/Chrome/User Data")];
  }
  const homes = [
    join(homedir(), ".config/google-chrome"),
    join(homedir(), ".config/chromium"),
    join(homedir(), ".config/microsoft-edge"),
  ];
  return isWsl() ? [...wslWindowsChromeHomes(), ...homes] : homes;
}

export function chromeTimeToIso(value) {
  if (value == null || value === 0 || value === 0n) return null;
  const micros = typeof value === "bigint" ? value : BigInt(Math.trunc(value));
  const milliseconds = Number((micros - CHROME_TO_UNIX_MICROSECONDS) / 1000n);
  const date = new Date(milliseconds);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function profileDirs(chromeHome) {
  if (!isDirectory(chromeHome)) return [];
  const profiles = [];
  const defaultProfile = join(chromeHome, "Default");
  if (isDirectory(defaultProfile)) profiles.push(defaultProfile);
  try {
    profiles.push(
      ...readdirSync(chromeHome, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && entry.name.startsWith("Profile "))
        .map((entry) => join(chromeHome, entry.name))
        .sort(),
    );
  } catch {}
  return profiles;
}

export function normalizeText(value) {
  return String(value ?? "").toLocaleLowerCase().replaceAll(" ", "");
}

export function expandKeywords(keyword) {
  const values = [normalizeText(keyword), ...String(keyword).trim().split(/\s+/).map(normalizeText)];
  return [...new Set(values.filter(Boolean))];
}

export function matchesKeyword(keyword, title, url) {
  const titleText = normalizeText(title);
  const urlText = normalizeText(url);
  return expandKeywords(keyword).some(
    (value) => titleText.includes(value) || urlText.includes(value),
  );
}

export function calculateMatchScore(keyword, title, url) {
  const values = expandKeywords(keyword);
  const titleText = normalizeText(title);
  const urlText = normalizeText(url);
  const complete = normalizeText(keyword);
  let score = 0;
  if (titleText.includes(complete)) score += 10;
  if (urlText.includes(complete)) score += 5;
  values.forEach((value, index) => {
    if (value === complete) return;
    const weight = 3 / (index + 1);
    if (titleText.includes(value)) score += weight;
    if (urlText.includes(value)) score += weight * 0.5;
  });
  return score;
}

function walkBookmarkNode(node, profile, keyword, pathParts, results) {
  const name = node?.name || "";
  if (node?.type === "url") {
    const url = node.url || "";
    if (matchesKeyword(keyword, name, url)) {
      results.push({
        title: name,
        url,
        source: "bookmark",
        profile,
        bookmark_path: pathParts.join(" / "),
        last_visit_time: null,
        match_score: calculateMatchScore(keyword, name, url),
      });
    }
    return;
  }
  const next = name ? [...pathParts, name] : pathParts;
  for (const child of node?.children ?? []) {
    if (child && typeof child === "object") {
      walkBookmarkNode(child, profile, keyword, next, results);
    }
  }
}

export function readBookmarks(profileDir, keyword) {
  const file = join(profileDir, "Bookmarks");
  if (!isFile(file)) return [];
  let data;
  try {
    data = JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    console.error(`Warning: 无法读取书签 ${file}: ${String(error)}`);
    return [];
  }
  const results = [];
  for (const [rootName, root] of Object.entries(data.roots ?? {})) {
    if (root && typeof root === "object") {
      walkBookmarkNode(root, basename(profileDir), keyword, [rootName], results);
    }
  }
  return results;
}

export function readHistory(profileDir, keyword, limit) {
  const historyFile = join(profileDir, "History");
  if (!isFile(historyFile)) return [];
  const tempDir = mkdtempSync(join(tmpdir(), "chrome-history-"));
  const copied = join(tempDir, `${basename(profileDir)}-History`);
  try {
    copyFileSync(historyFile, copied);
    const db = new DatabaseSync(copied, { readOnly: true });
    try {
      const values = expandKeywords(keyword);
      const where = values.map(() => "(lower(title) LIKE ? OR lower(url) LIKE ?)").join(" OR ");
      const params = values.flatMap((value) => [`%${value}%`, `%${value}%`]);
      const statement = db.prepare(
        `SELECT title, url, last_visit_time FROM urls WHERE ${where} ORDER BY last_visit_time DESC LIMIT ?`,
      );
      statement.setReadBigInts(true);
      const rows = statement.all(...params, BigInt(limit));
      return rows
        .filter((row) => matchesKeyword(keyword, row.title, row.url))
        .map((row) => ({
          title: row.title || "",
          url: row.url || "",
          source: "history",
          profile: basename(profileDir),
          bookmark_path: null,
          last_visit_time: chromeTimeToIso(row.last_visit_time),
          match_score: calculateMatchScore(keyword, row.title, row.url),
        }));
    } finally {
      db.close();
    }
  } catch (error) {
    console.error(`Warning: 无法查询历史记录 ${historyFile}: ${String(error)}`);
    return [];
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

export function dedupeAndSort(candidates, limit) {
  const best = new Map();
  for (const candidate of candidates) {
    if (!candidate.url) continue;
    const existing = best.get(candidate.url);
    if (
      !existing ||
      (existing.source === "history" && candidate.source === "bookmark") ||
      candidate.match_score > existing.match_score
    ) {
      best.set(candidate.url, candidate);
    }
  }
  return [...best.values()]
    .sort((left, right) => {
      const score = (right.match_score ?? 0) - (left.match_score ?? 0);
      if (score) return score;
      const source = (left.source === "bookmark" ? 0 : 1) - (right.source === "bookmark" ? 0 : 1);
      if (source) return source;
      return String(right.last_visit_time ?? "").localeCompare(String(left.last_visit_time ?? ""));
    })
    .slice(0, limit);
}

export function findCandidates(chromeHome, keywords, limit) {
  const candidates = [];
  const perProfileLimit = Math.max(limit * keywords.length * 2, 50);
  for (const profile of profileDirs(chromeHome)) {
    for (const keyword of keywords) {
      candidates.push(...readBookmarks(profile, keyword));
      candidates.push(...readHistory(profile, keyword, perProfileLimit));
    }
  }
  return dedupeAndSort(candidates, limit);
}

export function isProbablyArticle(url) {
  const normalized = String(url ?? "").toLowerCase();
  if (NOISE_PATTERNS.some((pattern) => normalized.includes(pattern))) return false;
  try {
    return new URL(normalized).pathname.replace(/\/+$/, "").length > 0;
  } catch {
    return false;
  }
}

export function filterCandidates(candidates, days, articlesOnly, now = new Date()) {
  const cutoff = days == null ? undefined : now.getTime() - days * 86_400_000;
  return candidates.filter((candidate) => {
    if (articlesOnly && !isProbablyArticle(candidate.url)) return false;
    if (cutoff == null || !candidate.last_visit_time) return true;
    const timestamp = Date.parse(candidate.last_visit_time);
    return !Number.isFinite(timestamp) || timestamp >= cutoff;
  });
}

function parseArgs(argv) {
  const options = { limit: 10, pretty: false, articlesOnly: false };
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--keywords") {
      options.keywords = [];
      while (index + 1 < argv.length && !argv[index + 1].startsWith("--")) {
        options.keywords.push(argv[++index]);
      }
    } else if (value === "--chrome-home") options.chromeHome = argv[++index];
    else if (value === "--limit") options.limit = Number(argv[++index]);
    else if (value === "--days") options.days = Number(argv[++index]);
    else if (value === "--articles-only") options.articlesOnly = true;
    else if (value === "--pretty") options.pretty = true;
    else if (value === "--help" || value === "-h") options.help = true;
    else positional.push(value);
  }
  options.keyword = positional[0];
  return options;
}

function usage() {
  return `用法: node find-history.mjs <keyword> [选项]
       node find-history.mjs --keywords <关键词...> [选项]

选项:
  --chrome-home <path>  Chrome 用户数据根目录
  --limit <n>           最多返回数，默认 10
  --days <n>            只保留最近 N 天
  --articles-only       过滤搜索页、登录页和首页
  --pretty              缩进 JSON`;
}

export function main(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  if (options.help) {
    console.log(usage());
    return 0;
  }
  const keywords = (options.keywords?.length ? options.keywords : [options.keyword])
    .filter(Boolean)
    .map((value) => value.trim())
    .filter(Boolean);
  if (!keywords.length) {
    console.error("Error: 必须提供 keyword 或 --keywords 参数");
    return 2;
  }
  if (!Number.isInteger(options.limit) || options.limit < 1) {
    console.error("Error: --limit 必须是正整数");
    return 2;
  }
  if (options.days != null && (!Number.isInteger(options.days) || options.days < 0)) {
    console.error("Error: --days 必须是非负整数");
    return 2;
  }

  const candidates = options.chromeHome
    ? [resolve(options.chromeHome)]
    : defaultChromeHomes().filter(isDirectory);
  if (!candidates.length) {
    console.error("Error: 找不到 Chrome 用户数据目录。已尝试:");
    defaultChromeHomes().forEach((home) => console.error(`  - ${home}`));
    console.error("\n  用 --chrome-home 显式指定路径。");
    return 2;
  }

  const rawLimit = options.articlesOnly || options.days != null
    ? Math.max(options.limit * 4, 40)
    : options.limit;
  let selectedHome = candidates[0];
  let found = [];
  for (const home of candidates) {
    const current = findCandidates(home, keywords, rawLimit);
    if (current.length) {
      selectedHome = home;
      found = current;
      break;
    }
  }
  const filtered = filterCandidates(found, options.days, options.articlesOnly).slice(
    0,
    options.limit,
  );
  console.log(
    JSON.stringify(
      {
        query: keywords.length > 1 ? keywords.join(" ") : keywords[0],
        keywords,
        chrome_home: selectedHome,
        filters: { days: options.days ?? null, articles_only: options.articlesOnly },
        candidates: filtered,
      },
      null,
      options.pretty ? 2 : undefined,
    ),
  );
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = main();
}
