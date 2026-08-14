#!/usr/bin/env node
import { accessSync, constants, readFileSync, realpathSync, readdirSync } from "node:fs";
import { cpus, homedir, machine, platform, totalmem } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { isDirectory, isFile } from "../../lib/fs.mjs";
import { VaultNotFoundError, configPath, findVault, loadVaultRegistry } from "../../lib/vault.mjs";

const REPOSITORY = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const MINIMUM_NODE = [22, 13, 0];

export function nodeVersionSupported(value) {
  const numbers = String(value).replace(/^v/, "").split(".").map(Number); if (numbers.some((number) => !Number.isFinite(number))) return false;
  for (let index = 0; index < MINIMUM_NODE.length; index += 1) { if (numbers[index] > MINIMUM_NODE[index]) return true; if (numbers[index] < MINIMUM_NODE[index]) return false; }
  return true;
}

function systemName(value = platform()) { return { darwin: "Darwin", linux: "Linux", win32: "Windows" }[value] || value; }

export function probePlatform({ platformName = platform(), architecture = machine(), memory = totalmem(), cpuCount = cpus().length } = {}) {
  const system = systemName(platformName); let isWsl = false;
  if (system === "Linux") { try { isWsl = readFileSync("/proc/version", "utf8").toLocaleLowerCase().includes("microsoft"); } catch {} }
  const appleSilicon = system === "Darwin" && ["arm64", "aarch64"].includes(architecture);
  const label = system === "Darwin" ? `macOS ${appleSilicon ? "Apple Silicon" : "Intel"}` : isWsl ? "Windows WSL2" : system === "Windows" ? "Windows（原生）" : system === "Linux" ? "Linux" : `${system}（未适配）`;
  return { activate_cmd: system === "Windows" ? ".venv\\Scripts\\Activate.ps1 (PowerShell) / .venv\\Scripts\\activate.bat (CMD)" : "source .venv/bin/activate", system, machine: architecture, label, is_wsl: isWsl, apple_silicon: appleSilicon, pkg_manager: system === "Darwin" ? "brew" : system === "Windows" ? "winget" : system === "Linux" ? "apt" : null, supported: ["Darwin", "Linux", "Windows"].includes(system), ram_gb: Math.round(memory / 1024 ** 3), cpu_count: cpuCount };
}

function executable(name, env = process.env) {
  if (name === "node" && isFile(process.execPath)) return process.execPath;
  const extensions = platform() === "win32" ? (env.PATHEXT || ".EXE;.CMD;.BAT").split(";") : [""];
  for (const directory of String(env.PATH || "").split(delimiter).filter(Boolean)) for (const extension of extensions) {
    const path = join(directory, `${name}${extension}`); try { accessSync(path, constants.X_OK); return path; } catch {}
  }
  return null;
}

function run(path, args, timeout = 10_000) {
  const result = spawnSync(path, args, { encoding: "utf8", timeout });
  return { ok: result.status === 0, stdout: result.stdout?.trim() || "", stderr: result.stderr?.trim() || "" };
}

export function probeTools(env = process.env) {
  const definitions = { node: "Node 运行时（必需）", npm: "Node workspace 依赖管理（必需）", uv: "保留 Python 后端的环境管理（按需）", ffmpeg: "音视频转码（按需）", git: "版本管理（建议）", "nvidia-smi": "NVIDIA GPU 查询" };
  return Object.fromEntries(Object.entries(definitions).map(([name, why]) => {
    const path = executable(name, env); const entry = { found: Boolean(path), path, why };
    if (path && ["node", "npm", "uv", "ffmpeg", "git"].includes(name)) { const output = run(path, name === "ffmpeg" ? ["-version"] : ["--version"]); if (output.ok) entry.version = output.stdout.split("\n")[0].slice(0, 80); }
    return [name, entry];
  }));
}

export function probeGpu(platformInfo, env = process.env) {
  if (platformInfo.apple_silicon) return { kind: "apple-metal", usable_for_asr: true, note: "Apple Silicon + Metal，mlx-whisper 可用 GPU 加速" };
  let path = executable("nvidia-smi", env); if (!path && platformInfo.system === "Windows" && isFile("C:\\Windows\\System32\\nvidia-smi.exe")) path = "C:\\Windows\\System32\\nvidia-smi.exe";
  if (!path) return { kind: "none", usable_for_asr: false, note: "未检测到 NVIDIA GPU，本地 ASR 只能跑 CPU" };
  const output = run(path, ["--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]); if (!output.ok) return { kind: "nvidia-broken", usable_for_asr: false, note: "nvidia-smi 执行失败" };
  const [name, memory, driver] = output.stdout.split("\n")[0].split(",").map((value) => value.trim()); return { kind: "nvidia", usable_for_asr: true, name, memory, driver, note: "faster-whisper 可走 CUDA（需 CUDA 12 + cuDNN 9）" };
}

export function probePythonBackends(platformInfo) {
  const venv = join(REPOSITORY, ".venv"); const python = join(venv, platformInfo.system === "Windows" ? "Scripts/python.exe" : "bin/python"); const info = { path: venv, exists: isDirectory(venv), python_ok: isFile(python) };
  if (!info.python_ok) return info;
  const version = run(python, ["--version"]); info.python_version = version.stdout || version.stderr;
  const capabilities = { "反爬平台适配": ["curl_cffi", "bs4", "lxml"], "B站": ["bilibili_api"], "公众号": ["markdownify"], "文档解析": ["docling", "markitdown"], "音视频转写": platformInfo.system === "Darwin" ? ["mlx_whisper"] : ["faster_whisper"], "音视频下载": ["yt_dlp"], "媒体底层库": ["media_to_text"] };
  const modules = [...new Set(Object.values(capabilities).flat())]; const source = `import importlib.util,json;print(json.dumps({m:importlib.util.find_spec(m) is not None for m in ${JSON.stringify(modules)}}))`;
  const probe = run(python, ["-c", source], 60_000); let found = {}; try { if (probe.ok) found = JSON.parse(probe.stdout); } catch {}
  info.capabilities = Object.fromEntries(Object.entries(capabilities).map(([name, items]) => [name, { ready: items.every((item) => found[item]), missing: items.filter((item) => !found[item]) }])); return info;
}

export function probeVault(env = process.env) {
  const file = configPath(env); const info = { env_KG_VAULT: env.KG_VAULT, config_path: file, config_exists: isFile(file) };
  try { const registry = loadVaultRegistry(file); info.registered = Object.keys(registry.paths); info.default = registry.defaultName; }
  catch (error) { info.config_error = error instanceof Error ? error.message : String(error); }
  try { info.resolved = findVault({ hint: REPOSITORY, env }); }
  catch (error) { if (!(error instanceof VaultNotFoundError)) throw error; info.resolve_error = error.message; }
  return info;
}

export function probeRegistration(bases = [
  resolve(REPOSITORY, "../..", ".agents", "skills"),
  join(homedir(), ".agents", "skills"),
  join(homedir(), ".claude", "skills"),
], repository = REPOSITORY) {
  const result = {};
  for (const base of bases) {
    const entry = { dir_exists: isDirectory(base), linked: false };
    if (entry.dir_exists) for (const child of readdirSync(base, { withFileTypes: true })) {
      if (!child.isSymbolicLink()) continue; try { if (realpathSync(join(base, child.name)) === realpathSync(repository)) { entry.linked = true; entry.link_name = child.name; break; } } catch {}
    }
    result[base] = entry;
  }
  return result;
}

export function buildDoctorData({ platformInfo = probePlatform(), tools = probeTools(), gpu = null, python = null, vault = null, registration = null } = {}) {
  const data = { repo: REPOSITORY, platform: platformInfo, gpu: gpu || probeGpu(platformInfo), tools, python_backends: python || probePythonBackends(platformInfo), vault: vault || probeVault(), registration: registration || probeRegistration(), blockers: [], notes: [] };
  if (!platformInfo.supported) data.blockers.push(`${platformInfo.system} 未适配（支持 macOS / Linux / WSL2 / Windows）`);
  if (!tools.node?.found) data.blockers.push("Node.js 未安装（必需，要求 >=22.13）");
  else if (!nodeVersionSupported(tools.node.version)) data.blockers.push(`Node.js 版本过低：${tools.node.version}（要求 >=22.13）`);
  if (!tools.npm?.found) data.blockers.push("npm 未安装（必需，用于 workspace 依赖与测试）");
  if (!tools.uv?.found) data.notes.push("uv 未安装：Node 核心能力不受影响；需要文档/转写/特殊平台 Python 后端时再安装。");
  if (!tools.ffmpeg?.found) data.notes.push(`ffmpeg 未安装：只有音视频转写需要。${platformInfo.system === "Darwin" ? "brew install ffmpeg" : platformInfo.system === "Windows" ? "winget install ffmpeg" : "sudo apt install -y ffmpeg"}`);
  if (!data.vault.resolved && !(data.vault.registered?.length > 1)) data.notes.push("知识库未配置；旧笔记走 kg-init，标准库走 kg-vault add。");
  if (platformInfo.ram_gb && platformInfo.ram_gb < 8) data.notes.push(`内存 ${platformInfo.ram_gb}GB，Whisper 建议 small/medium 模型。`);
  return data;
}

export function humanReport(data) {
  const lines = [`# 环境体检\n`, `平台: ${data.platform.label} (${data.platform.machine}) · ${data.platform.ram_gb}GB · ${data.platform.cpu_count} 核`, `GPU: ${data.gpu.kind} — ${data.gpu.note}`, "\n## Node 核心"];
  for (const name of ["node", "npm", "git"]) { const tool = data.tools[name]; lines.push(`  ${tool?.found ? "✅" : "❌"} ${name.padEnd(8)} ${tool?.version || tool?.why || "缺失"}`); }
  lines.push("\n## Python 可选后端"); const python = data.python_backends; lines.push(`  ${python.python_ok ? `✅ ${python.python_version}` : "○ 未创建 .venv（纯 Node 能力可正常用）"}`);
  for (const [name, state] of Object.entries(python.capabilities || {})) lines.push(`  ${state.ready ? "✅" : "○ "} ${name}${state.ready ? "" : `（缺 ${state.missing.join(", ")}）`}`);
  lines.push("\n## 知识库定位", data.vault.resolved ? `  ✅ ${data.vault.resolved}` : data.vault.registered?.length ? `  ○ 已注册 ${data.vault.registered.join(", ")}；多库由 AI 按 desc 路由` : "  ❌ 未配置");
  lines.push("\n## Skill 注册"); const links = Object.entries(data.registration).filter(([, value]) => value.linked); lines.push(...(links.length ? links.map(([base, value]) => `  ✅ ${join(base, value.link_name)} → 本仓库`) : ["  ○ 未在项目或用户级 skill 目录注册"]));
  if (data.blockers.length) lines.push("\n## 阻塞项", ...data.blockers.map((item) => `  ❌ ${item}`)); if (data.notes.length) lines.push("\n## 提示", ...data.notes.map((item) => `  · ${item}`));
  lines.push("\n---\nNode 入口默认可用；仅在需要文档解析、音视频转写或特殊平台适配时安装对应 Python 后端。"); return lines.join("\n");
}

export function main(argv = process.argv.slice(2)) { const { values } = parseArgs({ args: argv, options: { json: { type: "boolean" }, help: { type: "boolean", short: "h" } } }); if (values.help) { console.log("doctor.mjs [--json]"); return 0; } const data = buildDoctorData(); console.log(values.json ? JSON.stringify(data, null, 2) : humanReport(data)); return data.blockers.length ? 1 : 0; }
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
