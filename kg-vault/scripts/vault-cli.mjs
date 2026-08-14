#!/usr/bin/env node
import { existsSync, readdirSync, statSync } from "node:fs";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  VaultNotFoundError,
  absolutePath,
  configPath,
  findVault,
  loadVaultDescriptions,
  loadVaultRegistry,
  looksLikeVault,
  saveVaultRegistry,
} from "../../lib/vault.mjs";

const EXIT_OK = 0;
const EXIT_ERR = 1;
const EXIT_NO_UNIQUE_DEFAULT = 2;
const VAULT_DIRS = ["wiki", "raw", "assets"];
const VAULT_FILES = ["AGENTS.md", "index.md", "log.md"];

function usage() {
  return `用法:
  node vault-cli.mjs which
  node vault-cli.mjs list [--json]
  node vault-cli.mjs add <路径> [--name <别名>] [--desc <用途>]
  node vault-cli.mjs describe <别名> <用途>
  node vault-cli.mjs use <别名>
  node vault-cli.mjs remove <别名>
  node vault-cli.mjs doctor`;
}

function parseOptions(values) {
  const positional = [];
  const options = {};
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index];
    if (value === "--json") options.json = true;
    else if (value === "--name" || value === "--desc") {
      if (index + 1 >= values.length) throw new Error(`${value} 缺少值`);
      options[value.slice(2)] = values[++index];
    } else positional.push(value);
  }
  return { positional, options };
}

function wikiCount(root) {
  const start = join(root, "wiki");
  if (!existsSync(start)) return 0;
  let count = 0;
  const pending = [start];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const file = join(directory, entry.name);
      if (entry.isDirectory()) pending.push(file);
      else if (entry.isFile() && entry.name.endsWith(".md")) count += 1;
    }
  }
  return count;
}

function register(pathValue, name, desc, created = false) {
  const path = absolutePath(pathValue);
  const { paths, defaultName } = loadVaultRegistry();
  const descriptions = loadVaultDescriptions();
  const key = name || basename(path);
  if (paths[key] && paths[key] !== path) {
    console.error(`[错误] 别名 '${key}' 已被占用（指向 ${paths[key]}）`);
    console.error("       换个 --name，或先 remove 旧的");
    return EXIT_ERR;
  }
  paths[key] = path;
  if (desc != null) descriptions[key] = desc.trim();
  saveVaultRegistry(paths, defaultName, descriptions);
  console.log(`✅ ${created ? "已创建并注册" : "已注册"} '${key}' → ${path}`);
  if (Object.keys(paths).length > 1 && !defaultName) {
    console.log("   当前有多个库；AI 会按 desc 自动选择并显式传 --vault。");
  }
  return EXIT_OK;
}

function commandWhich() {
  try {
    console.log(findVault({ hint: fileURLToPath(import.meta.url) }));
    return EXIT_OK;
  } catch (error) {
    if (!(error instanceof VaultNotFoundError)) throw error;
    console.log(error.message);
    return EXIT_NO_UNIQUE_DEFAULT;
  }
}

function commandList(json) {
  const { paths, defaultName } = loadVaultRegistry();
  const descriptions = loadVaultDescriptions();
  if (json) {
    console.log(
      JSON.stringify(
        {
          default: defaultName,
          vaults: Object.entries(paths).map(([name, path]) => ({
            name,
            path,
            desc: descriptions[name] ?? "",
            default: name === defaultName,
            valid: looksLikeVault(path),
          })),
        },
        null,
        2,
      ),
    );
    return EXIT_OK;
  }
  if (Object.keys(paths).length === 0) {
    console.log("未注册任何知识库。已有知识库用 `add` 注册；没有知识库先用 kg-init 创建。");
    return EXIT_OK;
  }
  console.log(`# 已注册的知识库（配置：${configPath()}）\n`);
  for (const [name, path] of Object.entries(paths)) {
    const valid = looksLikeVault(path);
    const mark = name === defaultName ? "★" : " ";
    const extra = valid ? `  (${wikiCount(path)} 页 wiki)` : "  ← 路径无效";
    console.log(` ${mark} ${name.padEnd(14)} ${path}${extra}`);
    if (descriptions[name]) console.log(`                    ${descriptions[name]}`);
  }
  if (defaultName) console.log("\n★ = 默认库");
  return EXIT_OK;
}

function commandAdd(pathValue, options) {
  if (!pathValue) throw new Error("add 需要路径");
  const path = absolutePath(pathValue);
  if (!existsSync(path) || !statSync(path).isDirectory()) {
    console.error(`[错误] 目录不存在: ${path}`);
    return EXIT_ERR;
  }
  if (!looksLikeVault(path)) {
    console.error(`[错误] ${path} 不像知识库（需要 AGENTS.md 和 wiki/ 目录）`);
    console.error("       建库/改造旧笔记请先用 kg-init，完成后再 add");
    return EXIT_ERR;
  }
  return register(path, options.name, options.desc);
}

function commandDescribe(name, descParts) {
  const { paths, defaultName } = loadVaultRegistry();
  if (!name || !(name in paths)) {
    console.error(`[错误] 没有别名 '${name ?? ""}'。现有：${Object.keys(paths).join(", ") || "(空)"}`);
    return EXIT_ERR;
  }
  const desc = descParts.join(" ").trim();
  if (!desc) {
    console.error("[错误] 用途描述不能为空");
    return EXIT_ERR;
  }
  const descriptions = loadVaultDescriptions();
  descriptions[name] = desc;
  saveVaultRegistry(paths, defaultName, descriptions);
  console.log(`✅ 已更新 '${name}' 的用途描述：${desc}`);
  return EXIT_OK;
}

function commandUse(name) {
  const { paths } = loadVaultRegistry();
  if (!name || !(name in paths)) {
    console.error(`[错误] 没有别名 '${name ?? ""}'。现有：${Object.keys(paths).join(", ") || "(空)"}`);
    return EXIT_ERR;
  }
  saveVaultRegistry(paths, name);
  console.log(`✅ 默认库已切换为 '${name}' → ${paths[name]}`);
  return EXIT_OK;
}

function commandRemove(name) {
  const { paths, defaultName: currentDefault } = loadVaultRegistry();
  const descriptions = loadVaultDescriptions();
  if (!name || !(name in paths)) {
    console.error(`[错误] 没有别名 '${name ?? ""}'`);
    return EXIT_ERR;
  }
  const removed = paths[name];
  delete paths[name];
  delete descriptions[name];
  const defaultName = currentDefault === name ? null : currentDefault;
  saveVaultRegistry(paths, defaultName, descriptions);
  console.log(`✅ 已移除注册 '${name}'（目录未删除：${removed}）`);
  if (defaultName) console.log(`   当前默认库：${defaultName}`);
  else if (Object.keys(paths).length > 1) {
    console.log("   默认库已清除；AI 仍会按 desc 自动选择目标库。");
  }
  return EXIT_OK;
}

function commandDoctor() {
  console.log("# 配置检查\n");
  console.log(`配置文件: ${configPath()} ${existsSync(configPath()) ? "✅ 存在" : "✗ 不存在"}`);
  const env = process.env.KG_VAULT;
  console.log(
    env
      ? `KG_VAULT: ${env} ${looksLikeVault(env) ? "✅ 有效（会覆盖配置文件）" : "✗ 无效"}`
      : "KG_VAULT: 未设置（正常，配置文件优先级足够）",
  );
  const { paths, defaultName } = loadVaultRegistry();
  const descriptions = loadVaultDescriptions();
  console.log(`\n## 已注册 ${Object.keys(paths).length} 个库\n`);
  let problems = 0;
  for (const [name, path] of Object.entries(paths)) {
    const mark = name === defaultName ? "★" : " ";
    if (!looksLikeVault(path)) {
      console.log(` ${mark} ${name}: ${path}\n     ✗ 无效（缺 AGENTS.md 或 wiki/）`);
      problems += 1;
      continue;
    }
    const missing = [
      ...VAULT_FILES.filter((item) => !existsSync(join(path, item))),
      ...VAULT_DIRS.filter((item) => !existsSync(join(path, item))).map((item) => `${item}/`),
    ];
    console.log(
      ` ${mark} ${name}: ${path}\n     ✅ ${wikiCount(path)} 页 wiki${missing.length ? ` | 建议补: ${missing.join(", ")}` : ""}`,
    );
    if (Object.keys(paths).length > 1 && !descriptions[name]) {
      console.log("     ⚠️  缺用途描述；用 describe 补充后 AI 路由会更准确");
      problems += 1;
    }
    if (missing.length) problems += 1;
  }
  if (Object.keys(paths).length === 0) {
    console.log(" （空）→ 已有知识库用 add 注册；没有知识库先用 kg-init 创建");
    problems += 1;
  }
  console.log(`\n${problems === 0 ? "✅ 配置正常" : `⚠️  有 ${problems} 处需要注意`}`);
  return EXIT_OK;
}

export function main(argv = process.argv.slice(2)) {
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    console.log(usage());
    return argv.length ? EXIT_OK : EXIT_ERR;
  }
  const [command, ...values] = argv;
  const { positional, options } = parseOptions(values);
  switch (command) {
    case "which":
      return commandWhich();
    case "list":
      return commandList(Boolean(options.json));
    case "add":
      return commandAdd(positional[0], options);
    case "init":
      return commandAdd(positional[0], options);
    case "describe":
      return commandDescribe(positional[0], positional.slice(1));
    case "use":
      return commandUse(positional[0]);
    case "remove":
      return commandRemove(positional[0]);
    case "doctor":
      return commandDoctor();
    default:
      throw new Error(`未知命令: ${command}\n${usage()}`);
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === absolutePath(process.argv[1])) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = EXIT_ERR;
  }
}
