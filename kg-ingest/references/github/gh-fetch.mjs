#!/usr/bin/env node
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

function chinaTime() { return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "short", hourCycle: "h23" }).format(new Date()); }

export function runGh(args, { env = process.env, timeout = 120_000 } = {}) {
  const childEnv = { ...env }; const proxy = env.KG_GH_PROXY;
  if (proxy && !childEnv.HTTPS_PROXY) { childEnv.HTTPS_PROXY = proxy; childEnv.HTTP_PROXY = proxy; }
  const result = spawnSync("gh", args, { encoding: "utf8", timeout, env: childEnv });
  if (result.error?.code === "ENOENT") throw new Error("找不到 gh。安装后运行 gh auth login");
  if (result.error?.code === "ETIMEDOUT") throw new Error(`gh 超时（${timeout / 1000}s）`);
  if (result.status !== 0) {
    const detail = (result.stderr || "").trim(); if (/auth login|authentication/i.test(detail)) throw new Error("gh 未认证，请先运行 gh auth login");
    throw new Error(`gh 失败（exit ${result.status}）：${detail.slice(0, 300)}`);
  }
  return result.stdout;
}

function frontmatter(title, source, extra = {}) {
  const lines = ["---", `title: ${title}`, `source: ${source}`, "platform: GitHub", `fetched: ${chinaTime()}`];
  Object.entries(extra).forEach(([key, value]) => { if (value != null && value !== "" && !(Array.isArray(value) && !value.length)) lines.push(`${key}: ${value}`); });
  return [...lines, "---", ""];
}

export function starsMarkdown(repositories, language) {
  const filtered = repositories.filter((repo) => !language || String(repo.language || "").toLocaleLowerCase() === language.toLocaleLowerCase()).toSorted((a, b) => (b.stargazers_count || 0) - (a.stargazers_count || 0));
  const grouped = new Map(); filtered.forEach((repo) => { const key = repo.language || "其他"; grouped.set(key, [...(grouped.get(key) || []), repo]); });
  const groups = [...grouped].toSorted((a, b) => b[1].length - a[1].length); const lines = frontmatter(`GitHub Star 清单（${filtered.length} 个）`, "https://github.com/?tab=stars", { count: filtered.length });
  lines.push(`# GitHub Star（${filtered.length} 个）`, "", "## 语言分布", ""); groups.forEach(([name, repos]) => lines.push(`- ${name} · ${repos.length}`)); lines.push("");
  for (const [name, repos] of groups) { lines.push(`## ${name}`, ""); for (const repo of repos) { lines.push(`- **[${repo.full_name}](${repo.html_url})** ★${repo.stargazers_count || 0}${repo.description?.trim() ? ` — ${repo.description.trim()}` : ""}`); if (repo.topics?.length) lines.push(`  - \`${repo.topics.slice(0, 8).join("` `")}\``); } lines.push(""); }
  return lines.join("\n");
}

export function issueMarkdown(meta, comments = []) {
  const repo = meta.repository_url?.split("/repos/")[1] || new URL(meta.html_url).pathname.split("/").slice(1, 3).join("/"); const number = meta.number;
  const lines = frontmatter(meta.title || "", meta.html_url || "", { repo, number, state: meta.state, author: meta.user?.login, created: (meta.created_at || "").slice(0, 10), comments: meta.comments || 0 });
  lines.push(`# ${meta.title || ""}`, "", `> ${repo} #${number} · ${meta.state} · @${meta.user?.login || "?"} · ${(meta.created_at || "").slice(0, 10)}`, `> ${meta.html_url || ""}`, "");
  if (meta.labels?.length) lines.push(`**标签**：${meta.labels.map((label) => `\`${label.name}\``).join(" ")}`, ""); lines.push("## 正文", "", meta.body?.trim() || "_（空）_", "");
  if (comments.length) { lines.push(`## 讨论（${comments.length} 条）`, ""); comments.forEach((comment) => lines.push(`### @${comment.user?.login || "?"} · ${(comment.created_at || "").slice(0, 10)}`, "", comment.body?.trim() || "", "")); }
  return lines.join("\n");
}

function mineMarkdown(items) {
  const lines = frontmatter(`我提的 issue / PR（${items.length} 条）`, "https://github.com/issues?q=author%3A%40me", { count: items.length });
  lines.push(`# 我提的 issue / PR（${items.length} 条）`, "", "> 这些是你自己写下的问题和判断，比 star 更能反映实际踩过什么。", "");
  items.forEach((item) => { lines.push(`## [${item.repository.nameWithOwner}](${item.url}) · ${item.isPullRequest ? "PR" : "issue"}`, "", `**${item.title}**`, "", `> ${item.state} · ${(item.createdAt || "").slice(0, 10)}`, ""); const body = item.body?.trim(); if (body) lines.push(body.slice(0, 1200) + (body.length > 1200 ? "…" : ""), ""); }); return lines.join("\n");
}

function repoMarkdown(repo, readme) {
  const lines = frontmatter(repo.full_name || "", repo.html_url || "", { stars: repo.stargazers_count, language: repo.language, license: repo.license?.spdx_id, pushed: (repo.pushed_at || "").slice(0, 10) });
  lines.push(`# ${repo.full_name || ""}`, "", `> ★${repo.stargazers_count || 0} · ${repo.language || "-"} · 最后推送 ${(repo.pushed_at || "").slice(0, 10)}`, `> ${repo.html_url || ""}`, "", repo.description?.trim() || "", ""); if (repo.topics?.length) lines.push(`**Topics**：${repo.topics.map((topic) => `\`${topic}\``).join(" ")}`, ""); lines.push(readme ? "## README" : "_（没取到 README）_", ...(readme ? ["", readme.trim(), ""] : [""])); return lines.join("\n");
}

function parseCli(argv) {
  const command = argv[0]; const positionals = []; const options = {};
  for (let index = 1; index < argv.length; index += 1) { const value = argv[index]; if (value.startsWith("--")) { if (!argv[index + 1]) throw new Error(`${value} 缺少值`); options[value.slice(2)] = argv[++index]; } else positionals.push(value); }
  return { command, positionals, options };
}

export function main(argv = process.argv.slice(2), gh = runGh) {
  const { command, positionals, options } = parseCli(argv); if (!command || ["--help", "-h"].includes(command)) { console.log("gh-fetch.mjs stars|issue|mine|repo ... [--out file]"); return command ? 0 : 1; }
  let markdown;
  if (command === "stars") { const output = gh(["api", "user/starred", "--paginate", "--jq", ".[] | {full_name, description, language, stargazers_count, html_url, topics, pushed_at}"]); markdown = starsMarkdown(output.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)), options.language); }
  else if (command === "issue") {
    const target = positionals[0]; if (!target) throw new Error("issue 需要 owner/repo#123"); const spec = target.includes("#") ? target.replace("#", "/issues/") : target; const match = spec.match(/^(.+?)\/(?:issues|pull)\/(\d+)$/); if (!match) throw new Error("格式：owner/repo#123 或 owner/repo/issues/123");
    const meta = JSON.parse(gh(["api", `repos/${match[1]}/issues/${match[2]}`])); let comments = [];
    if (meta.comments) { const pages = JSON.parse(gh(["api", `repos/${match[1]}/issues/${match[2]}/comments`, "--paginate", "--slurp"])); comments = pages.flat(); }
    markdown = issueMarkdown(meta, comments);
  } else if (command === "mine") { const limit = Number(options.limit || 30); if (!Number.isInteger(limit) || limit < 1) throw new Error("--limit 必须是正整数"); markdown = mineMarkdown(JSON.parse(gh(["search", "issues", "--author=@me", `--limit=${limit}`, "--json", "repository,title,state,url,createdAt,isPullRequest,body"]))); }
  else if (command === "repo") { const target = positionals[0]; if (!target) throw new Error("repo 需要 owner/repo"); const repo = JSON.parse(gh(["api", `repos/${target}`])); let readme = ""; try { readme = gh(["api", `repos/${target}/readme`, "-H", "Accept: application/vnd.github.raw"]); } catch {} markdown = repoMarkdown(repo, readme); }
  else throw new Error(`未知命令: ${command}`);
  if (options.out) { mkdirSync(dirname(options.out), { recursive: true }); writeFileSync(options.out, markdown, "utf8"); console.error(`[ok] 写入 ${options.out}（${markdown.length} 字符）`); }
  else console.log(markdown); return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
