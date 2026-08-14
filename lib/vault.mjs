import {
  chmodSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join, parse, resolve } from "node:path";

const REQUIRED_FILES = ["AGENTS.md"];
const REQUIRED_DIRS = ["wiki"];

export class VaultNotFoundError extends Error {
  constructor(message) {
    super(message);
    this.name = "VaultNotFoundError";
  }
}

export function configPath(env = process.env) {
  const dir = env.KG_AGENT_CONFIG_DIR?.trim() || join(homedir(), ".kg-agent-config");
  return join(expandHome(dir), "config.json");
}

export function expandHome(value) {
  if (value === "~") return homedir();
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return join(homedir(), value.slice(2));
  }
  return value;
}

export function absolutePath(value) {
  return resolve(expandHome(String(value)));
}

function isFile(file) {
  try {
    return statSync(file).isFile();
  } catch {
    return false;
  }
}

function isDirectory(file) {
  try {
    return statSync(file).isDirectory();
  } catch {
    return false;
  }
}

export function looksLikeVault(value) {
  const root = absolutePath(value);
  return (
    isDirectory(root) &&
    REQUIRED_FILES.every((name) => isFile(join(root, name))) &&
    REQUIRED_DIRS.every((name) => isDirectory(join(root, name)))
  );
}

export function readConfig(file = configPath()) {
  if (!isFile(file)) return {};
  let value;
  try {
    value = JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new VaultNotFoundError(`配置文件 ${file} 不是合法 JSON：${error.message}`);
    }
    throw new VaultNotFoundError(`无法读取配置文件 ${file}：${String(error)}`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new VaultNotFoundError(`配置文件 ${file} 的顶层必须是 JSON 对象。`);
  }
  return value;
}

function parseDefault(value) {
  if (value == null) return null;
  if (typeof value !== "string") {
    throw new VaultNotFoundError("配置中的 vault.default 必须是字符串或 null。");
  }
  return value;
}

function stringMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => typeof item === "string")
      .map(([key, item]) => [String(key), item]),
  );
}

export function loadVaultRegistry(file = configPath()) {
  const data = readConfig(file);
  const vnode = data.vault;
  if (vnode && typeof vnode === "object" && !Array.isArray(vnode)) {
    if (vnode.paths && typeof vnode.paths === "object" && !Array.isArray(vnode.paths)) {
      return { paths: stringMap(vnode.paths), defaultName: parseDefault(vnode.default) };
    }
  }
  if (data.vaults && typeof data.vaults === "object" && !Array.isArray(data.vaults)) {
    const paths = stringMap(data.vaults);
    if (Object.keys(paths).length > 0) {
      return { paths, defaultName: parseDefault(data.default) };
    }
  }
  if (typeof vnode === "string") {
    return { paths: { default: vnode }, defaultName: "default" };
  }
  return { paths: {}, defaultName: null };
}

export function loadVaultDescriptions(file = configPath()) {
  const data = readConfig(file);
  const vnode = data.vault;
  if (!vnode || typeof vnode !== "object" || Array.isArray(vnode)) return {};
  return Object.fromEntries(
    Object.entries(vnode.descriptions ?? {})
      .filter(([, value]) => typeof value === "string" && value.trim())
      .map(([key, value]) => [String(key), value.trim()]),
  );
}

export function saveVaultRegistry(paths, defaultName, descriptions, file = configPath()) {
  const cleanPaths = Object.fromEntries(
    Object.entries(paths).map(([key, value]) => [String(key), expandHome(String(value))]),
  );
  if (defaultName != null && !(defaultName in cleanPaths)) {
    throw new Error(`默认库 '${defaultName}' 不在 paths 中`);
  }

  const data = readConfig(file);
  const previous =
    data.vault && typeof data.vault === "object" && !Array.isArray(data.vault)
      ? data.vault.descriptions
      : {};
  const sourceDescriptions = descriptions ?? previous ?? {};
  const cleanDescriptions = Object.fromEntries(
    Object.entries(sourceDescriptions)
      .filter(
        ([key, value]) =>
          key in cleanPaths && typeof value === "string" && value.trim().length > 0,
      )
      .map(([key, value]) => [String(key), value.trim()]),
  );

  data.version ??= 1;
  data.vault = {
    default: defaultName,
    paths: cleanPaths,
    descriptions: cleanDescriptions,
  };
  delete data.vaults;
  delete data.default;

  mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
  try {
    chmodSync(dirname(file), 0o700);
  } catch {}
  const temp = join(dirname(file), `.${parse(file).base}.${process.pid}.tmp`);
  writeFileSync(temp, `${JSON.stringify(data, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  try {
    chmodSync(temp, 0o600);
  } catch {}
  renameSync(temp, file);
  return file;
}

function configuredVault(file = configPath()) {
  const { paths, defaultName } = loadVaultRegistry(file);
  if (Object.keys(paths).length === 0) return undefined;
  if (defaultName) {
    if (!(defaultName in paths)) {
      throw new VaultNotFoundError(`配置的默认库 '${defaultName}' 不存在。`);
    }
    const selected = absolutePath(paths[defaultName]);
    if (looksLikeVault(selected)) return selected;
    throw new VaultNotFoundError(
      `配置里的库 '${defaultName}' 指向 ${selected}，但那里不像知识库。`,
    );
  }

  const descriptions = loadVaultDescriptions(file);
  const valid = Object.entries(paths)
    .map(([name, value]) => [name, absolutePath(value)])
    .filter(([, value]) => looksLikeVault(value));
  if (valid.length === 1) return valid[0][1];
  if (valid.length > 1) {
    const lines = valid.map(
      ([name, value]) => `  · ${name}: ${value}${descriptions[name] ? ` — ${descriptions[name]}` : ""}`,
    );
    throw new VaultNotFoundError(
      `配置里有多个知识库但未指定默认：\n${lines.join("\n")}` +
        "\n\n【给 AI 的指示】运行 kg-vault list --json，按 desc 判断本次内容最适合的库，" +
        "然后给原命令显式加 --vault <路径>。不要仅因为有多个库就询问用户。",
    );
  }
  throw new VaultNotFoundError("配置里的知识库路径都已失效，请询问用户新的路径。");
}

export function walkUp(start, limit = 8) {
  let current = absolutePath(start);
  for (let index = 0; index < limit; index += 1) {
    if (looksLikeVault(current)) return current;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return undefined;
}

export function findVault({ hint, explicit, cwd = process.cwd(), env = process.env } = {}) {
  if (explicit) {
    const selected = absolutePath(explicit);
    if (looksLikeVault(selected)) return selected;
    throw new VaultNotFoundError(
      `--vault 指向 ${selected}，但那里不像知识库（需要 AGENTS.md 和 wiki/ 目录）。`,
    );
  }

  if (env.KG_VAULT?.trim()) {
    const selected = absolutePath(env.KG_VAULT.trim());
    if (looksLikeVault(selected)) return selected;
    throw new VaultNotFoundError(
      `环境变量 KG_VAULT 指向 ${selected}，但那里不像知识库（需要 AGENTS.md 和 wiki/ 目录）。`,
    );
  }

  const selected = configuredVault(configPath(env));
  if (selected) return selected;
  const fromCwd = walkUp(cwd);
  if (fromCwd) return fromCwd;
  if (hint) {
    const fromHint = walkUp(dirname(absolutePath(hint)));
    if (fromHint) return fromHint;
  }

  const { paths } = loadVaultRegistry(configPath(env));
  const known = Object.keys(paths).length
    ? `\n配置里已有这些库（但当前都不可用，可能路径已变）：\n${Object.entries(paths)
        .map(([name, value]) => `  · ${name}: ${value}`)
        .join("\n")}`
    : "";
  throw new VaultNotFoundError(
    `找不到知识库 —— 不知道该把内容写到哪里。\n${known}\n` +
      "\n【给 AI 的指示】不要猜测路径，直接问用户：「你的知识库在哪个目录？」\n" +
      "拿到路径后用下面任一方式继续：\n" +
      "  1. 本次临时：   加 --vault /path/to/vault 参数\n" +
      "  2. 长期注册：   node kg-vault/scripts/vault-cli.mjs add /path/to/vault\n" +
      "  3. 环境变量：   export KG_VAULT=/path/to/vault\n" +
      "\n知识库需包含 AGENTS.md 和 wiki/ 目录。" +
      "\n没有现成的库？先用 kg-init 建库，再用 kg-vault 注册路径。",
  );
}

export function countWikiPages(root) {
  const base = join(root, "wiki");
  if (!existsSync(base)) return 0;
  let count = 0;
  const pending = [base];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      if (entry.isDirectory()) pending.push(join(current, entry.name));
      else if (entry.isFile() && entry.name.endsWith(".md")) count += 1;
    }
  }
  return count;
}
