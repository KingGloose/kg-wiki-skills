#!/usr/bin/env node
import { mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { isFile, readJson, writeJsonAtomic } from "../../../lib/fs.mjs";

const GATEWAY = "https://i.weread.qq.com/api/agent/gateway";
const VENDOR_SKILL = resolve(dirname(fileURLToPath(import.meta.url)), "../../../vendor/WeChatReading/skills/SKILL.md");
const MINIMUM_INTERVAL = 1200;
const CACHE_TTL = 6 * 3600;
const TOUCHED_SECONDS = 300;
const HALFWAY_MIN = 5;
const HALFWAY_MAX = 85;

function sleep(milliseconds) { return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds)); }
function chinaTime(date = new Date()) { return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "short", hourCycle: "h23" }).format(date); }

export function skillVersion(path = VENDOR_SKILL) {
  try { const text = readFileSync(path, "utf8"); return text.match(/skill_version["']?\s*[:=]\s*["']?(\d+\.\d+\.\d+)/)?.[1] || text.match(/version:\s*(\d+\.\d+\.\d+)/)?.[1] || "1.0.4"; } catch { return "1.0.4"; }
}

export function apiKey(env = process.env) {
  if (env.WEREAD_API_KEY?.trim()) return env.WEREAD_API_KEY.trim();
  const result = spawnSync("security", ["find-generic-password", "-a", "weread", "-s", "kg-weread-apikey", "-w"], { encoding: "utf8", timeout: 15_000 });
  if (result.status === 0 && result.stdout.trim()) return result.stdout.trim();
  throw new Error("没找到微信读书 API Key。设置 WEREAD_API_KEY，或存入 macOS Keychain 的 kg-weread-apikey/weread。");
}

export function createWereadClient({ fetchImpl = fetch, key = null, version = skillVersion(), minimumInterval = MINIMUM_INTERVAL, sleepImpl = sleep } = {}) {
  let lastCall = 0;
  const call = async (apiName, params = {}, retries = 3) => {
    const gap = Date.now() - lastCall; if (gap < minimumInterval) await sleepImpl(minimumInterval - gap); lastCall = Date.now();
    const response = await fetchImpl(GATEWAY, { method: "POST", headers: { authorization: `Bearer ${key || apiKey()}`, "content-type": "application/json" }, body: JSON.stringify({ api_name: apiName, skill_version: version, ...params }), signal: AbortSignal.timeout(40_000) });
    const body = await response.text(); let data; try { data = JSON.parse(body); } catch { data = null; }
    if (response.status === 401) throw new Error("API Key 无效或已失效，请重新获取");
    if (([429, 499].includes(response.status) || body.includes("-2014")) && retries > 0) { const wait = (4 - retries) * 3000 + 3000; console.error(`[..] 频率超限，等 ${wait / 1000}s 重试`); await sleepImpl(wait); return call(apiName, params, retries - 1); }
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${body.slice(0, 200)}`); if (!data) throw new Error("接口返回的不是合法 JSON"); if (data.errcode != null && data.errcode !== 0) throw new Error(`接口返回 errcode=${data.errcode}: ${data.errmsg || body}`); return data;
  };
  return { call };
}

function cachePath(env = process.env) { return join(env.XDG_CACHE_HOME || join(homedir(), ".cache"), "kg-weread", "progress.json"); }
function loadCache(env = process.env) { const value = readJson(cachePath(env), {}); return Date.now() / 1000 - (value._ts || 0) < CACHE_TTL ? value.data || {} : {}; }
function saveCache(data, env = process.env) { try { writeJsonAtomic(cachePath(env), { _ts: Date.now() / 1000, data }); } catch {} }
export function formatDuration(seconds = 0) { if (seconds < 60) return `${seconds} 秒`; if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`; return `${(seconds / 3600).toFixed(1)} 小时`; }
function daysSince(timestamp) { return timestamp ? Math.floor((Date.now() / 1000 - timestamp) / 86400) : null; }

export function classifyShelf(rows) {
  const finished = rows.filter((row) => row.finished && row.reading_time >= TOUCHED_SECONDS);
  const marked_only = rows.filter((row) => row.finished && row.reading_time < TOUCHED_SECONDS);
  const untouched = rows.filter((row) => !row.finished && row.reading_time < TOUCHED_SECONDS);
  const halfway = rows.filter((row) => !row.finished && row.reading_time >= TOUCHED_SECONDS && row.progress >= HALFWAY_MIN && row.progress <= HALFWAY_MAX);
  const invested = rows.filter((row) => !row.finished && row.reading_time >= 3600 && !halfway.includes(row));
  const other = rows.filter((row) => ![...finished, ...marked_only, ...untouched, ...halfway, ...invested].includes(row));
  return { finished, marked_only, untouched, halfway, invested, other };
}

function shelfMarkdown(books, albums, rows) {
  const groups = classifyShelf(rows); const total = rows.reduce((sum, row) => sum + row.reading_time, 0);
  const lines = ["---", `title: 书架体检（${books.length} 本）`, "source: 微信读书", "platform: 微信读书", `fetched: ${chinaTime()}`, `books: ${books.length}`, `finished: ${groups.finished.length}`, "---", "", `# 书架体检 · ${books.length} 本${albums.length ? ` + ${albums.length} 个有声` : ""}`, "", `> 累计阅读 ${formatDuration(total)} · 真读完 ${groups.finished.length} 本 · 没真正翻过 ${groups.untouched.length} 本`, "", "> 判断依据是 readingTime/progress；readUpdateTime 只是书架条目更新时间。", ""];
  const block = (name, items, note = "") => {
    if (!items.length) return; lines.push(`## ${name} · ${items.length} 本`, ""); if (note) lines.push(`> ${note}`, "");
    items.toSorted((a, b) => b.reading_time - a.reading_time).forEach((row) => { const bits = []; if (row.progress) bits.push(`${row.progress}%`); if (row.reading_time) bits.push(formatDuration(row.reading_time)); if (row.chapter) bits.push(`第 ${row.chapter} 章`); const days = daysSince(row.read_time || row.shelf_time); if (days != null) bits.push(`${days} 天前`); const title = row.title.length > 34 ? `${row.title.slice(0, 34)}…` : row.title; lines.push(`- **${title}**${bits.length ? `（${bits.join(" · ")}）` : ""}`); }); lines.push("");
  };
  block("读完了", groups.finished); block("标记了已读，但没什么阅读时长", groups.marked_only, "可能是在其他媒介读完，或只做了标记。"); block("读了一半搁下的", groups.halfway, "已经投入过，接着读的成本较低。"); block("投入不少但没读完", groups.invested, "累计超过 1 小时。"); block("囤了没真正翻过", groups.untouched, "累计阅读不足 5 分钟。"); block("其他", groups.other);
  return lines.join("\n");
}

async function commandShelf(client, refresh) {
  const shelf = await client.call("/shelf/sync"); const books = shelf.books || []; if (!books.length) return "书架是空的。"; const cache = refresh ? {} : loadCache(); const rows = [];
  for (let index = 0; index < books.length; index += 1) {
    const book = books[index]; const id = String(book.bookId); let progress = cache[id];
    if (!progress) { try { progress = (await client.call("/book/getprogress", { bookId: id })).book || {}; cache[id] = progress; } catch (error) { console.error(`[warn] ${book.title?.slice(0, 16)} 进度查询失败：${error.message}`); progress = {}; } }
    rows.push({ title: book.title || "", author: book.author || "", bookId: id, finished: Boolean(book.finishReading), shelf_time: book.readUpdateTime, progress: progress.progress || 0, reading_time: progress.readingTime || 0, started: Boolean(progress.isStartReading), chapter: progress.chapterIdx, read_time: progress.updateTime });
  }
  saveCache(cache); return shelfMarkdown(books, shelf.albums || [], rows);
}

async function resolveBook(client, keyword) {
  if (/^[A-Za-z0-9_]{6,}$/.test(keyword)) return [keyword, keyword]; const books = (await client.call("/shelf/sync")).books || []; const matches = books.filter((book) => (book.title || "").includes(keyword));
  if (!matches.length) throw new Error(`书架里没找到「${keyword}」`); if (matches.length > 1) throw new Error(`「${keyword}」匹配到多本：${matches.map((book) => `${book.title}(${book.bookId})`).join("、")}`); return [matches[0].bookId, matches[0].title || ""];
}

function popularNotesMarkdown(title, id, items) {
  const lines = ["---", `title: ${title} · 社区热门划线`, `source: https://weread.qq.com/web/reader/${id}`, "platform: 微信读书", `book_id: ${id}`, `fetched: ${chinaTime()}`, "kind: 社区热门（非本人划线）", `marks: ${items.length}`, "---", "", `# ${title} · 社区热门划线`, "", "> ⚠️ 这不是你的划线，只能当作快速预览，不能混成个人阅读所得。", ""];
  items.forEach((item) => { if (item.markText?.trim()) lines.push(`> ${item.markText.trim().replace(/\n/g, "\n> ")}`, item.totalCount || item.count ? `> — ${item.totalCount || item.count} 人划过` : "", ""); }); return lines.join("\n");
}

async function commandNotes(client, keyword) {
  const [id, title] = await resolveBook(client, keyword); const marksData = await client.call("/book/bookmarklist", { bookId: id }); const marks = marksData.updated || marksData.bookmarks || []; let reviews = [];
  try { reviews = (await client.call("/review/list", { bookId: id, listType: 11 })).reviews || []; } catch (error) { console.error(`[warn] 想法拉取失败：${error.message}`); }
  if (!marks.length && !reviews.length) { let items = []; try { items = (await client.call("/book/bestbookmarks", { bookId: id })).items || []; } catch {} return items.length ? popularNotesMarkdown(title, id, items) : `# ${title}\n\n_这本书没有划线，社区热门划线也没取到。_\n`; }
  const chapters = new Map(); marks.forEach((mark) => { const key = mark.chapterUid || 0; chapters.set(key, [...(chapters.get(key) || []), mark]); }); const titles = {};
  try { const info = await client.call("/book/chapterinfo", { bookId: id }); (info.data?.[0]?.updated || []).forEach((chapter) => { titles[chapter.chapterUid] = chapter.title || ""; }); } catch {}
  const lines = ["---", `title: ${title} · 划线摘录`, `source: https://weread.qq.com/web/reader/${id}`, "platform: 微信读书", `book_id: ${id}`, `fetched: ${chinaTime()}`, `marks: ${marks.length}`, `thoughts: ${reviews.length}`, "---", "", `# ${title}`, "", `> 划线 ${marks.length} 条${reviews.length ? ` · 想法 ${reviews.length} 条` : ""}`, ""];
  for (const [chapter, items] of [...chapters].sort(([a], [b]) => Number(a) - Number(b))) { lines.push(`## ${titles[chapter] || (chapter ? `第 ${chapter} 章` : "未分章")}`, ""); items.toSorted((a, b) => String(a.range || "").localeCompare(String(b.range || ""))).forEach((mark) => { if (mark.markText?.trim()) lines.push(`> ${mark.markText.trim().replace(/\n/g, "\n> ")}`, ""); }); }
  if (reviews.length) { lines.push("## 我的想法", ""); reviews.forEach((item) => { const review = item.review || {}; const content = review.content || item.content || ""; if (review.abstract) lines.push(`> ${review.abstract.trim()}`, ""); if (content.trim()) lines.push(`**想法**：${content.trim()}`, ""); }); }
  lines.push("---", "", "_原文摘录，沉淀时请提炼而非照搬。_"); return lines.join("\n");
}

async function commandNotebooks(client) {
  const books = (await client.call("/user/notebooks")).books || []; if (!books.length) return "还没有任何笔记。"; const rows = books.map((item) => ({ note: item.noteCount || 0, review: item.reviewCount || 0, mark: item.bookmarkCount || 0, title: item.book?.title || "" })).toSorted((a, b) => b.note - a.note);
  return [`# 有笔记的书（${rows.length} 本）`, "", "| 书名 | 划线 | 想法 | 书签 |", "|---|---|---|---|", ...rows.map((row) => `| ${row.title} | ${row.note} | ${row.review} | ${row.mark} |`)].join("\n");
}

async function commandStats(client, mode) {
  const data = await client.call("/readdata/detail", { mode }); const lines = [`# 阅读统计 · ${mode}`, "", `- 总时长：${formatDuration(data.totalReadTime || 0)}`, `- 有效阅读天数：${data.readDays || 0}`, `- 日均：${formatDuration(data.dayAverageReadTime || 0)}`];
  if (data.compare != null) lines.push(`- 与上一周期比：${data.compare >= 0 ? "+" : ""}${(data.compare * 100).toFixed(0)}%`); if (data.readLongest?.length) lines.push("", "## 读得最多", "", ...data.readLongest.slice(0, 10).map((item) => `- ${item.book?.title || "?"} — ${formatDuration(item.readTime || 0)}`)); return lines.join("\n");
}

function parseCli(argv) {
  const command = argv[0]; const positionals = []; const options = {};
  for (let index = 1; index < argv.length; index += 1) { const value = argv[index]; if (value === "--refresh") options.refresh = true; else if (value.startsWith("--")) { if (!argv[index + 1]) throw new Error(`${value} 缺少值`); options[value.slice(2)] = argv[++index]; } else positionals.push(value); }
  return { command, positionals, options };
}

export async function main(argv = process.argv.slice(2), client = createWereadClient()) {
  const { command, positionals, options } = parseCli(argv); if (!command || ["--help", "-h"].includes(command)) { console.log("weread.mjs shelf|notes|notebooks|stats ... [--out file]"); return command ? 0 : 1; }
  let markdown; if (command === "shelf") markdown = await commandShelf(client, options.refresh); else if (command === "notes") { if (!positionals[0]) throw new Error("notes 需要书名或 bookId"); markdown = await commandNotes(client, positionals[0]); } else if (command === "notebooks") markdown = await commandNotebooks(client); else if (command === "stats") { const mode = options.mode || "monthly"; if (!["weekly", "monthly", "annually", "overall"].includes(mode)) throw new Error("--mode 不支持"); markdown = await commandStats(client, mode); } else throw new Error(`未知命令: ${command}`);
  if (options.out) { mkdirSync(dirname(options.out), { recursive: true }); const { writeFileSync } = await import("node:fs"); writeFileSync(options.out, markdown, "utf8"); console.error(`[ok] 写入 ${options.out}（${markdown.length} 字符）`); } else console.log(markdown); return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { main().then((code) => { process.exitCode = code; }, (error) => { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; }); }
