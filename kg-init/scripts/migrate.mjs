#!/usr/bin/env node
import { chmodSync, copyFileSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile, walkFiles } from "../../lib/fs.mjs";
import { expandHome } from "../../lib/vault.mjs";

const TEMPLATES = resolve(dirname(fileURLToPath(import.meta.url)), "../templates");
const NEW_DIRECTORIES = ["wiki", "raw", "assets"];
const NEW_FILES = ["AGENTS.md", "index.md", "log.md"];
const SCRIPT_FILES = ["scripts/lib-imgcompress.sh", "scripts/compress-images.sh", "scripts/fix-refs.mjs", "scripts/setup.sh", "scripts/hooks/pre-commit"];
const KEEP_ROOT = new Set([".git", ".gitignore", ".obsidian", ".trash", ".DS_Store", "node_modules", ".venv", "__pycache__", ".vscode", ".idea", "scripts"]);

function human(bytes) {
  let value = bytes;
  for (const unit of ["B", "KB", "MB", "GB", "TB"]) { if (value < 1024 || unit === "TB") return unit === "B" ? `${value.toFixed(0)}${unit}` : `${value.toFixed(1)}${unit}`; value /= 1024; }
}

function itemStats(path) {
  if (isFile(path)) return { size: statSync(path).size, files: 1 };
  const files = walkFiles(path); return { size: files.reduce((sum, file) => { try { return sum + statSync(file).size; } catch { return sum; } }, 0), files: files.length };
}

export function survey(root) {
  const toArchive = []; const keep = []; const already = [];
  for (const item of readdirSync(root, { withFileTypes: true }).toSorted((a, b) => a.name.localeCompare(b.name))) {
    if (KEEP_ROOT.has(item.name) || item.name.startsWith(".")) keep.push(item.name);
    else if (item.name === "archive" || NEW_DIRECTORIES.includes(item.name) || NEW_FILES.includes(item.name)) already.push(item.name);
    else { const path = join(root, item.name); const stats = itemStats(path); toArchive.push({ name: item.name, is_dir: item.isDirectory(), ...stats }); }
  }
  return {
    root, to_archive: toArchive, keep_at_root: keep, already_llm_wiki: already,
    missing_dirs: NEW_DIRECTORIES.filter((name) => !isDirectory(join(root, name))),
    missing_files: NEW_FILES.filter((name) => !isFile(join(root, name))),
    missing_scripts: SCRIPT_FILES.filter((name) => !isFile(join(root, name))),
    needs_gitignore: !isFile(join(root, ".gitignore")),
  };
}

function plan(root) {
  const data = survey(root); const size = data.to_archive.reduce((sum, item) => sum + item.size, 0); const files = data.to_archive.reduce((sum, item) => sum + item.files, 0);
  console.log(`# 改造计划：${basename(root)}\n\n目录: ${root}\n\n> **本命令只看不动。** 确认后用 \`apply <目录> --confirm\` 执行。\n`);
  console.log("## 策略\n\n采用「整体归档 + 向前新建」：旧内容原样移入 `archive/`，新知识进入 `wiki/`，旧知识按需蒸馏，不批量重写。\n\n## 会做什么\n");
  if (data.to_archive.length) {
    console.log(`1. 移动 ${data.to_archive.length} 项（${files} 个文件，${human(size)}）到 \`archive/\`：`);
    data.to_archive.slice(0, 20).forEach((item) => console.log(`   · ${item.name}${item.is_dir ? "/" : ""}（${item.files} 文件，${human(item.size)}）`));
  } else console.log("1. 无需归档：根目录没有待整理内容。");
  console.log(`2. 新建缺失目录：${data.missing_dirs.join(", ") || "无"}`);
  console.log(`3. 从模板创建：${data.missing_files.join(", ") || "无"}`);
  console.log(`4. 安装图片治理工具：${data.missing_scripts.join(", ") || "无"}`);
  console.log("5. 改造后由 AI 扫 archive 标题、整理 index 唤醒条目。\n");
  console.log("## 不会做什么\n\n- 不修改笔记正文。\n- 不删除任何文件。\n- 不覆盖已有 LLM Wiki 文件。\n- 不动版本控制与编辑器目录。\n");
  console.log("## 回滚\n\n改造前先提交 git 或完整备份目录；可用 `rollback <目录>` 查看非破坏性的回滚清单。\n");
  console.log(`执行前可演练：\n\n\`\`\`bash\n../bin/kg-node kg-init/scripts/migrate.mjs apply "${root}" --confirm --dry-run\n\`\`\``);
  return 0;
}

function copyTemplate(source, target, executable = false) {
  mkdirSync(dirname(target), { recursive: true }); copyFileSync(source, target); if (executable) chmodSync(target, 0o755);
}

export function applyMigration(root, { confirm = false, dryRun = false, log = console.log, error = console.error } = {}) {
  if (!confirm) { error("[错误] 拒绝执行：必须带 --confirm；请先运行 plan。"); return 1; }
  if (!isDirectory(TEMPLATES)) { error(`[错误] 找不到模板目录 ${TEMPLATES}`); return 1; }
  const data = survey(root); const action = (description, run) => { log(`${dryRun ? "[演练] " : ""}${description}`); if (!dryRun) run(); };
  if (data.to_archive.length) {
    action("创建 archive/", () => mkdirSync(join(root, "archive"), { recursive: true }));
    for (const item of data.to_archive) {
      const destination = join(root, "archive", item.name);
      if (isFile(destination) || isDirectory(destination)) { error(`[跳过] archive/${item.name} 已存在`); continue; }
      action(`移动 ${item.name} → archive/`, () => renameSync(join(root, item.name), destination));
    }
  }
  data.missing_dirs.forEach((name) => action(`新建目录 ${name}/`, () => mkdirSync(join(root, name), { recursive: true })));
  data.missing_files.forEach((name) => {
    const source = join(TEMPLATES, name); if (!isFile(source)) { error(`[跳过] 模板里没有 ${name}`); return; }
    action(`复制模板 ${name}`, () => copyTemplate(source, join(root, name)));
  });
  data.missing_scripts.forEach((name) => {
    const source = join(TEMPLATES, name); if (!isFile(source)) { error(`[跳过] 模板里没有 ${name}`); return; }
    action(`安装 ${name}`, () => copyTemplate(source, join(root, name), true));
  });
  if (data.needs_gitignore && isFile(join(TEMPLATES, "gitignore"))) action("新建 .gitignore", () => copyTemplate(join(TEMPLATES, "gitignore"), join(root, ".gitignore")));
  if (!dryRun && isFile(join(root, "log.md"))) {
    const date = new Date().toISOString().slice(0, 10); const current = readFileSync(join(root, "log.md"), "utf8");
    const entry = `\n## [${date}] setup | LLM Wiki 改造初始化\n\n- 由 kg-init 执行「整体归档 + 向前新建」。\n- 归档 ${data.to_archive.length} 项（${data.to_archive.reduce((sum, item) => sum + item.files, 0)} 个文件，${human(data.to_archive.reduce((sum, item) => sum + item.size, 0))}）到 \`archive/\`，正文未修改。\n- 安装图片治理工具链（${data.missing_scripts.length} 个文件）。\n`;
    writeFileSync(join(root, "log.md"), current + entry, "utf8"); log("在 log.md 记录本次改造");
  }
  log(`\n${dryRun ? "演练结束（未改动任何文件）" : "✅ 改造完成"}`);
  if (!dryRun) log(`下一步：调整 AGENTS.md；运行 scripts/setup.sh；用 extract-topics.mjs 扫 archive；通过 kg-vault 注册 ${root}。`);
  return 0;
}

function rollback(root) {
  const data = survey(root);
  console.log(`# 回滚清单：${basename(root)}\n\n本命令只展示，不执行。\n`);
  console.log("1. 先确认改造后 `wiki/`、`raw/`、`assets/` 是否已有新内容，并单独备份。");
  console.log("2. 将 archive/ 中的原目录逐项移回根目录；遇到同名目标时停止，不覆盖。");
  console.log("3. 仅删除本次新建且仍为空/未修改的模板文件和目录。");
  console.log("4. 若使用 git，优先查看 `git status` 和改造提交，通过 `git revert <commit>` 回滚已提交改造。");
  console.log(`\n当前 archive: ${isDirectory(join(root, "archive")) ? "存在" : "不存在"}；当前待归档根项目: ${data.to_archive.length}。`);
  return 0;
}

function parseCli(argv) {
  const [command, pathValue, ...rest] = argv;
  return { command, pathValue, confirm: rest.includes("--confirm"), dryRun: rest.includes("--dry-run") };
}

export function main(argv = process.argv.slice(2)) {
  const { command, pathValue, confirm, dryRun } = parseCli(argv);
  if (!command || ["--help", "-h"].includes(command)) { console.log("migrate.mjs plan|apply|rollback <目录> [--confirm] [--dry-run]"); return command ? 0 : 1; }
  const root = resolve(expandHome(pathValue || "")); if (!pathValue || !isDirectory(root)) { console.error(`[错误] 目录不存在: ${root}`); return 1; }
  if (command === "plan") return plan(root); if (command === "apply") return applyMigration(root, { confirm, dryRun }); if (command === "rollback") return rollback(root); throw new Error(`未知命令: ${command}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
