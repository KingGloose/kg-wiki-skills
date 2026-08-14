#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { walkFiles } from "../../lib/fs.mjs";

const REPOSITORY = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const KNOWN_VARIABLES = new Set(["HOME", "PATH", "PWD", "SHELL", "USER", "LOCALAPPDATA", "KG_VAULT", "VIRTUAL_ENV", "WSL_DISTRO_NAME", "WIN_IP", "BASH_SOURCE", "OSTYPE", "PYTHONPATH", "SESSDATA"]);

export function bashBlocks(text) {
  const blocks = []; const lines = text.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    if (!/^\s*```(?:bash|sh|shell|console)\s*$/.test(lines[index])) continue;
    const start = index + 2; const content = [];
    for (index += 1; index < lines.length && !lines[index].trim().startsWith("```"); index += 1) content.push(lines[index]);
    blocks.push([start, content.join("\n")]);
  }
  return blocks;
}

function issue(file, line, kind, severity, text, why, fix) { return { file, line, kind, severity, text, why, fix }; }

export function checkSkill(path, repository = REPOSITORY) {
  const text = readFileSync(path, "utf8"); const file = relative(repository, path).split("\\").join("/"); const issues = [];
  if (!text.startsWith("---\n")) issues.push(issue(file, 1, "missing-frontmatter", "error", text.split("\n")[0] || "", "缺少 YAML frontmatter，Agent 不会发现这个 skill", "添加 name 和 description"));
  else {
    const end = text.indexOf("\n---\n", 4); const frontmatter = end >= 0 ? text.slice(4, end) : ""; const name = frontmatter.match(/^name:\s*(\S+)\s*$/m); const description = frontmatter.match(/^description:\s*(.+)$/m);
    if (end < 0 || !name || !description) issues.push(issue(file, 1, "invalid-frontmatter", "error", "YAML frontmatter", "frontmatter 必须包含非空 name 和 description", "补全 frontmatter"));
    else if (name[1] !== basename(dirname(path))) issues.push(issue(file, 2, "skill-name-mismatch", "error", name[1], `skill 名称与目录 ${basename(dirname(path))} 不一致`, `改为 ${basename(dirname(path))}`));
  }
  const explained = new Set([...text.matchAll(/`\$\{?([A-Z][A-Z_]+)\}?`\s*[=＝]/g), ...text.matchAll(/\$\{?([A-Z][A-Z_]+)\}?\s*(?:=|指|表示|就是)/g)].map((match) => match[1]));
  for (const [lineNumber, block] of bashBlocks(text)) {
    block.split("\n").forEach((raw, offset) => {
      const line = raw.trim(); if (!line || line.startsWith("#")) return; const number = lineNumber + offset;
      if (/\bcd\s+["']?kg-wiki-skills\b/.test(line)) issues.push(issue(file, number, "hardcoded-repo-name", "error", line, "写死仓库目录名，软链或其他工作目录会失败", "改用相对 SKILL.md 的路径"));
      for (const match of line.matchAll(/\$\{?([A-Z][A-Z_]{1,})\}?/g)) if (!KNOWN_VARIABLES.has(match[1]) && !explained.has(match[1])) issues.push(issue(file, number, "undefined-var", "error", line, `用了 $${match[1]} 但文档没解释`, "定义变量或改用相对路径"));
      const userPath = line.match(/\/(?:Users|home)\/[a-zA-Z0-9_.-]+\//); if (userPath) issues.push(issue(file, number, "absolute-user-path", "error", line, `写死用户目录 ${userPath[0]}`, "改用相对路径或 ~"));
      const linkPath = line.match(/~\/\.(?:agents|claude)\/skills\/[a-zA-Z0-9_-]+\//); if (linkPath) issues.push(issue(file, number, "depends-on-link-name", "warn", line, `依赖全局软链名 ${linkPath[0]}`, "优先用相对 SKILL.md 的路径"));
      const vaultPath = line.match(/(?:^|\s)(?:\.\.\/)+(?:raw|wiki|assets)(?:\/|\s|$)/); if (vaultPath) issues.push(issue(file, number, "assumes-skills-inside-vault", "error", line, "假设 skill 仓库位于知识库内部，会写错位置", "使用解析后的 vault 路径"));
    });
  }
  return issues;
}

export function lintDocs(repository = REPOSITORY) {
  const skills = walkFiles(repository, (path) => basename(path) === "SKILL.md" && /^kg-[^/]+$/.test(basename(dirname(path))));
  const issues = skills.flatMap((path) => checkSkill(path, repository));
  return { skills_checked: skills.length, issues, errors: issues.filter((item) => item.severity === "error").length, warnings: issues.filter((item) => item.severity === "warn").length };
}

export function main(argv = process.argv.slice(2)) {
  const { values } = parseArgs({ args: argv, options: { json: { type: "boolean" }, help: { type: "boolean", short: "h" } } }); if (values.help) { console.log("lint-docs.mjs [--json]"); return 0; }
  const result = lintDocs(); if (values.json) console.log(JSON.stringify(result, null, 2));
  else {
    console.log(`# SKILL.md 发现与路径检查\n\n检查了 ${result.skills_checked} 个 skill`);
    if (!result.issues.length) console.log("\n✅ 没有发现问题。所有命令都不依赖工作目录、软链名或私人绝对路径。");
    else result.issues.forEach((item) => console.log(`\n${item.severity === "error" ? "❌" : "⚠️"} ${item.file}:${item.line} [${item.kind}]\n  命令: ${item.text}\n  原因: ${item.why}\n  修法: ${item.fix}`));
  }
  return result.errors ? 1 : 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
