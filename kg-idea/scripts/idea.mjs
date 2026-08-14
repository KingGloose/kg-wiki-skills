#!/usr/bin/env node
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { isFile, walkFiles } from "../../lib/fs.mjs";
import { VaultNotFoundError, findVault } from "../../lib/vault.mjs";

const IDEAS = "ideas";

export function safeName(title) {
  return (String(title).replace(/[/\\:*?"<>|]/g, "-").trim() || "未命名").slice(0, 80);
}

function chinaTime(date = new Date()) {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}`;
}

function ideasDir(vault) {
  const directory = join(vault, IDEAS);
  mkdirSync(directory, { recursive: true });
  return directory;
}

export function parseIdea(path) {
  const text = readFileSync(path, "utf8");
  const meta = { title: basename(path, ".md"), path, body: text };
  const created = text.match(/^>\s*\*\*记于\*\*[：:]\s*(\S+)/m);
  if (created) meta.created = created[1];
  const topics = text.match(/^>\s*\*\*主题\*\*[：:]\s*(.+)$/m);
  if (topics) meta.topics = topics[1].split(/[、,，]/u).map((item) => item.trim()).filter(Boolean);
  const graduated = text.match(/^>\s*\*\*已毕业\*\*[：:]\s*\[\[([^\]]+)\]\]/m);
  if (graduated) meta.graduated_to = graduated[1];
  const body = text.replace(/^>.*$/gm, "");
  meta.links = [...body.matchAll(/\[\[([^\]|]+)/g)].map((match) => match[1]);
  meta.has_followup = text.includes("## 追问") || text.includes("## 补充");
  return meta;
}

export function loadIdeas(vault) {
  return walkFiles(ideasDir(vault), (path) => path.endsWith(".md") && !["readme.md", "index.md"].includes(basename(path).toLowerCase()))
    .filter((path) => dirname(path) === ideasDir(vault))
    .flatMap((path) => {
      try { return [parseIdea(path)]; } catch { return []; }
    });
}

function parseCli(argv) {
  const args = [...argv];
  let vault;
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "--vault") {
      if (index + 1 >= args.length) throw new Error("--vault 缺少路径");
      vault = args[index + 1];
      args.splice(index, 2);
      break;
    }
  }
  const command = args.shift();
  const positionals = [];
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (["--json", "--random"].includes(value)) options[value.slice(2)] = true;
    else if (["--body", "--topics", "--links", "--quote", "--source", "--section", "--days", "--to"].includes(value)) {
      if (index + 1 >= args.length) throw new Error(`${value} 缺少值`);
      options[value.slice(2)] = args[++index];
    } else if (value.startsWith("--")) throw new Error(`未知参数: ${value}`);
    else positionals.push(value);
  }
  return { command, positionals, options, vault };
}

function ideaPath(vault, title) {
  return join(ideasDir(vault), `${safeName(title)}.md`);
}

function commandNew(vault, title, options) {
  if (!title) throw new Error("new 需要标题");
  const path = ideaPath(vault, title);
  if (isFile(path)) {
    console.error(`⚠ 已存在同名灵感：${basename(path)}`);
    console.error(`   要补充内容用：idea.mjs append "${title}" --body "..."`);
    return 1;
  }
  const lines = [`# ${title}`, "", `> **记于**：${chinaTime()}`];
  if (options.topics) lines.push(`> **主题**：${options.topics}`);
  if (options.source) lines.push(`> **触发**：${options.source}`);
  lines.push("", options.body || "（还没写正文）", "");
  if (options.quote) lines.push("原话：", `> ${options.quote}`, "");
  if (options.links) {
    const links = options.links.split(",").map((item) => item.trim()).filter(Boolean).map((item) => `[[${item}]]`).join("、");
    lines.push(`关联：${links}`, "");
  }
  writeFileSync(path, lines.join("\n"), "utf8");
  console.log(JSON.stringify({ ok: true, path, rel: `${IDEAS}/${basename(path)}` }));
  return 0;
}

function commandAppend(vault, title, options) {
  const path = ideaPath(vault, title);
  if (!isFile(path)) { console.error(`✗ 找不到灵感「${title}」`); return 1; }
  if (!options.body) throw new Error("append 需要 --body");
  appendFileSync(path, `\n## ${options.section || "补充"}（${chinaTime()}）\n\n${options.body}\n`, "utf8");
  console.log(`✓ 已追加到 ${IDEAS}/${basename(path)}`);
  return 0;
}

function commandList(vault, options) {
  let rows = loadIdeas(vault);
  if (options.days != null) {
    const days = Number(options.days);
    if (!Number.isInteger(days) || days < 0) throw new Error("--days 必须是非负整数");
    const cutoff = new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
    rows = rows.filter((row) => (row.created || "9999") >= cutoff);
  }
  rows.sort((left, right) => String(right.created || "").localeCompare(String(left.created || "")));
  if (options.json) {
    console.log(JSON.stringify(rows.map(({ body, path, ...row }) => ({ ...row, path })), null, 2));
    return 0;
  }
  if (!rows.length) { console.log("灵感库还是空的"); return 0; }
  console.log(`# 灵感 · ${rows.length} 条\n`);
  for (const row of rows) {
    const flags = [];
    if (row.graduated_to) flags.push("已毕业");
    else if (!row.has_followup) flags.push("待追问");
    if (row.links.length) flags.push(`${row.links.length} 链`);
    console.log(`  ${(row.created || "?").slice(0, 10)}  ${row.title}${flags.length ? `  [${flags.join(" · ")}]` : ""}`);
    if (row.topics) console.log(`              主题：${row.topics.join("、")}`);
  }
  return 0;
}

export function findGhosts(vault) {
  const rows = loadIdeas(vault);
  const existing = new Set(rows.map((row) => row.title));
  walkFiles(join(vault, "wiki"), (path) => path.endsWith(".md")).forEach((path) => existing.add(basename(path, ".md")));
  const ghost = new Map();
  for (const row of rows) {
    for (const link of row.links) {
      const name = link.split("/").at(-1).replace(/\.md$/, "").trim();
      if (name && !existing.has(name)) ghost.set(name, [...(ghost.get(name) || []), row.title]);
    }
  }
  return [...ghost].map(([name, referred_by]) => ({ name, referred_by, count: referred_by.length })).sort((a, b) => b.count - a.count);
}

function commandGhosts(vault, options) {
  const rows = findGhosts(vault);
  if (options.json) { console.log(JSON.stringify(rows, null, 2)); return 0; }
  if (!rows.length) { console.log("没有幽灵 —— 所有双链都指向已存在的页"); return 0; }
  console.log(`# 幽灵 · ${rows.length} 个提过但没展开的\n`);
  for (const row of rows) {
    console.log(`  ${row.name}（被 ${row.count} 处提到）`);
    row.referred_by.slice(0, 3).forEach((title) => console.log(`      ← ${title}`));
  }
  return 0;
}

function commandNext(vault, options) {
  const rows = loadIdeas(vault).filter((row) => !row.graduated_to);
  if (!rows.length) { console.log("灵感库里没有可发散的（都毕业了或者是空的）"); return 0; }
  const pending = rows.filter((row) => !row.has_followup);
  const pool = pending.length ? pending : rows;
  const pick = options.random ? pool[Math.floor(Math.random() * pool.length)] : pool.toSorted((a, b) => String(a.created || "").localeCompare(String(b.created || "")))[0];
  if (options.json) {
    console.log(JSON.stringify({ title: pick.title, created: pick.created, topics: pick.topics, links: pick.links, body: pick.body, rel: `${IDEAS}/${basename(pick.path)}`, never_followed_up: !pick.has_followup }, null, 2));
  } else console.log(pick.body);
  return 0;
}

function commandShow(vault, title) {
  const path = ideaPath(vault, title);
  if (!isFile(path)) {
    const candidates = loadIdeas(vault).map((row) => row.title).filter((item) => item.includes(title)).slice(0, 5);
    console.error(`✗ 找不到「${title}」${candidates.length ? `，你是指：${candidates.join("、")}？` : ""}`);
    return 1;
  }
  console.log(readFileSync(path, "utf8"));
  return 0;
}

function commandGraduate(vault, title, options) {
  const path = ideaPath(vault, title);
  if (!isFile(path)) { console.error(`✗ 找不到灵感「${title}」`); return 1; }
  if (!options.to) throw new Error("graduate 需要 --to");
  if (!isFile(join(vault, options.to))) { console.error(`✗ 目标沉淀页不存在：${options.to}\n   先把 wiki 页写好，再来毕业`); return 1; }
  const text = readFileSync(path, "utf8");
  if (text.includes("**已毕业**")) { console.error(`⚠ 「${title}」已经毕业过了`); return 1; }
  const lines = text.split("\n");
  let lastMeta = 1;
  lines.slice(0, 12).forEach((line, index) => { if (line.startsWith("> ")) lastMeta = index; });
  lines.splice(lastMeta + 1, 0, `> **已毕业**：[[../${options.to}]]（${chinaTime().slice(0, 10)}）—— 想清楚了，沉淀在那边`);
  writeFileSync(path, lines.join("\n"), "utf8");
  console.log(`✓ 「${title}」已标记毕业 → ${options.to}`);
  return 0;
}

export function main(argv = process.argv.slice(2)) {
  const { command, positionals, options, vault: explicit } = parseCli(argv);
  if (!command || ["--help", "-h"].includes(command)) {
    console.log("idea.mjs [--vault path] new|append|list|ghosts|next|show|graduate ...");
    return command ? 0 : 1;
  }
  let vault;
  try { vault = findVault({ hint: fileURLToPath(import.meta.url), explicit }); }
  catch (error) { if (!(error instanceof VaultNotFoundError)) throw error; console.error(`✗ ${error.message}`); return 2; }
  const title = positionals[0];
  const commands = {
    new: () => commandNew(vault, title, options), append: () => commandAppend(vault, title, options),
    list: () => commandList(vault, options), ghosts: () => commandGhosts(vault, options),
    next: () => commandNext(vault, options), show: () => commandShow(vault, title || ""),
    graduate: () => commandGraduate(vault, title, options),
  };
  if (!commands[command]) throw new Error(`未知命令: ${command}`);
  return commands[command]();
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try { process.exitCode = main(); }
  catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; }
}
