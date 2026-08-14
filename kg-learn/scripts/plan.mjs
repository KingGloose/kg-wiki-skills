#!/usr/bin/env node
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile, readJson, walkFiles, writeJsonAtomic } from "../../lib/fs.mjs";
import { VaultNotFoundError, findVault } from "../../lib/vault.mjs";

export function slugify(title) {
  return String(title).trim().replace(/[\\/:*?"<>|\s]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "").slice(0, 50) || "plan";
}

function now() {
  return new Date().toLocaleString("sv-SE", { hourCycle: "h23" }).slice(0, 16);
}

function parseCli(argv) {
  const args = [...argv];
  let vault;
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "--vault") { if (!args[index + 1]) throw new Error("--vault 缺少路径"); vault = args[index + 1]; args.splice(index, 2); break; }
  }
  const command = args.shift();
  const positionals = [];
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (["--steps", "--domain", "--why", "--note", "--minutes", "--summary"].includes(value)) {
      if (!args[index + 1]) throw new Error(`${value} 缺少值`);
      options[value.slice(2)] = args[++index];
    } else if (value.startsWith("--")) throw new Error(`未知参数: ${value}`);
    else positionals.push(value);
  }
  return { command, positionals, options, vault };
}

export function createPlanStore(vault) {
  const directory = join(vault, "learning");
  const pathFor = (slug) => join(directory, `${slug}.json`);
  const load = (slug) => {
    const path = pathFor(slug);
    if (!isFile(path)) throw new Error(`找不到计划: ${slug}（用 list 看现有计划）`);
    try { return JSON.parse(readFileSync(path, "utf8")); }
    catch (error) { throw new Error(`计划 ${slug} 不是合法 JSON：${error instanceof Error ? error.message : String(error)}`); }
  };
  const save = (plan) => { mkdirSync(directory, { recursive: true }); writeJsonAtomic(pathFor(plan.slug), plan); };
  return { directory, pathFor, load, save };
}

function commandNew(store, title, options) {
  if (!title) throw new Error("new 需要标题");
  const slug = slugify(title);
  if (isFile(store.pathFor(slug))) throw new Error(`计划已存在: ${slug}（用 show 查看，或换个标题）`);
  const steps = String(options.steps || "").split("|").map((item) => item.trim()).filter(Boolean);
  if (!steps.length) throw new Error("需要 --steps「步骤1|步骤2|...」");
  const plan = { slug, title, domain: options.domain || "", created: now(), status: "active", why: options.why || "", steps: steps.map((text, index) => ({ n: index + 1, text, done: false, done_at: null, note: "" })), notes: [], sessions: [] };
  store.save(plan);
  console.log(`✅ 已创建计划 \`${slug}\`（${steps.length} 步）\n   文件: learning/${slug}.json`);
  plan.steps.forEach((step) => console.log(`   ${step.n}. ${step.text}`));
  return 0;
}

function commandList(store) {
  if (!isDirectory(store.directory)) { console.log("还没有学习计划。用 `plan.mjs new` 创建。"); return 0; }
  const plans = walkFiles(store.directory, (path) => path.endsWith(".json") && dirname(path) === store.directory).flatMap((path) => {
    const plan = readJson(path, null); return plan ? [plan] : [];
  });
  if (!plans.length) { console.log("还没有学习计划。用 `plan.mjs new` 创建。"); return 0; }
  const line = (plan) => {
    const done = plan.steps.filter((step) => step.done).length;
    const minutes = (plan.sessions || []).reduce((sum, session) => sum + Number(session.minutes || 0), 0);
    return `  ${plan.slug.padEnd(32)} ${"█".repeat(done)}${"░".repeat(plan.steps.length - done)} ${done}/${plan.steps.length}  累计 ${minutes} 分钟  ${plan.domain || ""}`;
  };
  const active = plans.filter((plan) => plan.status === "active");
  const archived = plans.filter((plan) => plan.status !== "active");
  if (active.length) { console.log("# 进行中\n"); active.forEach((plan) => console.log(line(plan))); }
  if (archived.length) { console.log("\n# 已归档\n"); archived.forEach((plan) => console.log(line(plan))); }
  return 0;
}

function commandShow(store, slug) {
  const plan = store.load(slug);
  const done = plan.steps.filter((step) => step.done).length;
  console.log(`# ${plan.title}\n\n状态: ${plan.status} | 进度 ${done}/${plan.steps.length} | 创建 ${plan.created}`);
  if (plan.domain) console.log(`领域: ${plan.domain}`);
  if (plan.why) console.log(`为什么学: ${plan.why}`);
  console.log("\n## 步骤\n");
  plan.steps.forEach((step) => { console.log(`  ${step.done ? "✅" : "⬜"} ${step.n}. ${step.text}`); if (step.note) console.log(`      收获: ${step.note}`); });
  if (plan.notes?.length) { console.log("\n## 过程记录（误解 / 卡点 / 啊哈时刻）\n"); plan.notes.forEach((note) => console.log(`  · [${note.at}] ${note.text}`)); }
  if (plan.sessions?.length) {
    const total = plan.sessions.reduce((sum, session) => sum + Number(session.minutes || 0), 0);
    console.log(`\n## 学习会话（共 ${plan.sessions.length} 次 / ${total} 分钟）\n`);
    plan.sessions.slice(-6).forEach((session) => console.log(`  · ${session.at}  ${session.minutes ?? "?"} 分钟${session.summary ? `  — ${session.summary}` : ""}`));
  }
  return 0;
}

function commandDone(store, slug, stepValue, options) {
  const plan = store.load(slug);
  const stepNumber = Number(stepValue);
  if (!Number.isInteger(stepNumber)) throw new Error("步骤号必须是整数");
  const step = plan.steps.find((item) => item.n === stepNumber);
  if (!step) throw new Error(`没有第 ${stepValue} 步（共 ${plan.steps.length} 步）`);
  step.done = true; step.done_at = now(); if (options.note) step.note = options.note; store.save(plan);
  const done = plan.steps.filter((item) => item.done).length;
  console.log(`✅ 第 ${stepNumber} 步完成：${step.text}\n   进度 ${done}/${plan.steps.length}`);
  if (done === plan.steps.length) console.log("\n🎉 全部步骤完成！建议回顾 notes、沉淀认知收获，再用 `plan.mjs archive` 归档。");
  return 0;
}

function commandNote(store, slug, options) {
  if (!options.note) throw new Error("需要 --note 内容");
  const plan = store.load(slug); plan.notes ??= []; plan.notes.push({ at: now(), text: options.note }); store.save(plan);
  console.log(`✅ 已记录（该计划共 ${plan.notes.length} 条过程记录）`); return 0;
}

function commandSession(store, slug, options) {
  const minutes = Number(options.minutes);
  if (!Number.isInteger(minutes) || minutes <= 0) throw new Error("--minutes 必须是正整数");
  const plan = store.load(slug); plan.sessions ??= []; plan.sessions.push({ at: now(), minutes, summary: options.summary || "" }); store.save(plan);
  const total = plan.sessions.reduce((sum, session) => sum + Number(session.minutes || 0), 0);
  console.log(`✅ 已记录本次会话（${minutes} 分钟，累计 ${total} 分钟）`); return 0;
}

function commandArchive(store, slug) {
  const plan = store.load(slug); plan.status = "archived"; plan.archived_at = now(); store.save(plan);
  console.log(`✅ 已归档 \`${slug}\`\n   提醒：归档前确认认知收获已沉淀进 wiki（计划本身不是知识）`); return 0;
}

export function main(argv = process.argv.slice(2)) {
  const { command, positionals, options, vault: explicit } = parseCli(argv);
  if (!command || ["--help", "-h"].includes(command)) { console.log("plan.mjs [--vault path] new|list|show|done|note|session|archive ..."); return command ? 0 : 1; }
  let vault;
  try { vault = findVault({ hint: fileURLToPath(import.meta.url), explicit }); }
  catch (error) { if (!(error instanceof VaultNotFoundError)) throw error; console.error(`[错误] ${error.message}`); return 2; }
  const store = createPlanStore(vault);
  const [first, second] = positionals;
  const commands = { new: () => commandNew(store, first, options), list: () => commandList(store), show: () => commandShow(store, first), done: () => commandDone(store, first, second, options), note: () => commandNote(store, first, options), session: () => commandSession(store, first, options), archive: () => commandArchive(store, first) };
  if (!commands[command]) throw new Error(`未知命令: ${command}`);
  return commands[command]();
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; }
}
