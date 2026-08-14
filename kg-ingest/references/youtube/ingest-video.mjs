#!/usr/bin/env node
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { VaultNotFoundError, expandHome, findVault } from "../../../lib/vault.mjs";

const DEFAULT_LANGUAGES = ["zh-Hans", "zh-CN", "zh", "en", "en-orig"];
const SKILLS_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

export function sanitize(name) { return (String(name).replace(/[\\/:*?"<>|\n\r\t]/g, "_").trim() || "video").slice(0, 60); }
export function formatDuration(seconds) { const value = Number(seconds); if (!Number.isFinite(value)) return ""; const hours = Math.floor(value / 3600); const minutes = Math.floor(value % 3600 / 60); const rest = Math.floor(value % 60); return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}` : `${minutes}:${String(rest).padStart(2, "0")}`; }

export function cleanVtt(vtt) {
  const output = [];
  for (const raw of String(vtt).split(/\r?\n/)) {
    let line = raw.trim(); if (!line || /^(WEBVTT|Kind:|Language:|NOTE)/.test(line) || line.includes("-->") || /^\d+$/.test(line)) continue;
    line = line.replace(/<\d{2}:\d{2}:\d{2}\.\d{3}>/g, "").replace(/<\/?c[^>]*>/g, "").replace(/<[^>]+>/g, "").trim(); if (!line) continue;
    if (output.at(-1) === line) continue; if (output.length && line.startsWith(output.at(-1))) output[output.length - 1] = line; else output.push(line);
  }
  return output.join("\n").trim();
}

function command(binary, args, { timeout = 120_000 } = {}) {
  const result = spawnSync(binary, args, { encoding: "utf8", timeout });
  if (result.error?.code === "ENOENT") throw new Error(`找不到 ${binary}`); if (result.error?.code === "ETIMEDOUT") throw new Error(`${binary} 超时`);
  return { code: result.status ?? 1, stdout: result.stdout || "", stderr: result.stderr || "" };
}

export function getInfo(url, run = command) {
  const result = run("yt-dlp", ["--dump-json", "--skip-download", "--no-warnings", url]); if (result.code) throw new Error("获取视频信息失败（链接无效、私有、需登录或受地区限制）");
  let data; try { data = JSON.parse(result.stdout.split(/\r?\n/).find(Boolean)); } catch (error) { throw new Error(`解析视频信息失败：${error instanceof Error ? error.message : String(error)}`); }
  const rawDate = data.upload_date || ""; const uploadDate = rawDate.length === 8 ? `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6)}` : rawDate;
  return { id: data.id || "", title: data.title || "", channel: data.channel || data.uploader || "", duration: formatDuration(data.duration), duration_sec: data.duration || 0, upload_date: uploadDate, url: data.webpage_url || url, description: (data.description || "").trim(), view_count: data.view_count, subtitles: Object.keys(data.subtitles || {}).sort(), auto_captions: Object.keys(data.automatic_captions || {}).sort() };
}

export function trySubtitles(url, languages, run = command) {
  const directory = mkdtempSync(join(tmpdir(), "yt-sub-"));
  try {
    for (const language of languages) for (const [flag, tag] of [["--write-subs", "人工"], ["--write-auto-subs", "自动"]]) {
      readdirSync(directory).forEach((name) => rmSync(join(directory, name), { force: true }));
      const result = run("yt-dlp", [flag, "--sub-langs", language, "--sub-format", "vtt", "--skip-download", "--no-warnings", "-o", join(directory, "%(id)s"), url]);
      const file = readdirSync(directory).find((name) => name.endsWith(".vtt")); if (file) { const text = cleanVtt(readFileSync(join(directory, file), "utf8")); if (text) return { text, tag: `${language}(${tag})` }; }
      if (result.stderr.includes("429")) { console.error(`[warn] ${language} 触发 YouTube 限流，跳过`); break; }
    }
    return null;
  } finally { rmSync(directory, { recursive: true, force: true }); }
}

function runAsr(url, model, run = command) {
  const directory = mkdtempSync(join(tmpdir(), "yt-asr-"));
  try {
    const download = run("yt-dlp", ["-x", "--audio-format", "mp3", "--no-warnings", "-o", join(directory, "audio.%(ext)s"), url], { timeout: 600_000 }); if (download.code) throw new Error("音频下载失败");
    const file = readdirSync(directory).find((name) => name.startsWith("audio.")); if (!file) throw new Error("未找到下载的音频文件"); console.error(`[ok] 音频 ${(statSync(join(directory, file)).size / 1048576).toFixed(1)} MB，开始本地转写`);
    const args = [join(SKILLS_ROOT, "bin", "kg-py"), "kg-media-to-text/scripts/to-text.py", join(directory, file), "--json"]; if (model) args.push("--model", model);
    const result = run(args[0], args.slice(1), { timeout: 7_200_000 }); if (result.code) throw new Error(result.stderr.trim() || "本地转写失败"); return JSON.parse(result.stdout);
  } finally { rmSync(directory, { recursive: true, force: true }); }
}

export function buildMarkdown(info, body, source) {
  const lines = [`# ${info.title}`, "", `- 频道: ${info.channel}`, `- 时长: ${info.duration}`, `- 上传日期: ${info.upload_date}`, `- 链接: ${info.url}`, `- 文本来源: ${source}`, `- 摄入日期: ${new Date().toISOString().slice(0, 10)}`];
  if (info.view_count) lines.splice(4, 0, `- 播放量: ${info.view_count}`); lines.push("", "---", "", "## 简介", "", info.description || "（无简介）", "", "---", "", `## 正文（${source}）`, "", body); return `${lines.join("\n")}\n`;
}

function parseCli(argv) {
  const positionals = []; const options = {};
  for (let index = 0; index < argv.length; index += 1) { const value = argv[index]; if (["--asr", "--stdout"].includes(value)) options[value.slice(2)] = true; else if (value.startsWith("--")) { if (!argv[index + 1]) throw new Error(`${value} 缺少值`); options[value.slice(2)] = argv[++index]; } else positionals.push(value); }
  return { url: positionals[0], options };
}

export function main(argv = process.argv.slice(2), run = command) {
  const { url: input, options } = parseCli(argv); if (!input || ["--help", "-h"].includes(input)) { console.log("ingest-video.mjs <YouTube URL|ID> [--lang ...] [--asr] [--model ...] [--stdout] [--out file] [--vault path]"); return input ? 0 : 1; }
  const url = !input.startsWith("http") && /^[\w-]{11}$/.test(input) ? `https://www.youtube.com/watch?v=${input}` : input; console.error(`[..] 获取视频信息 ${url}`); const info = getInfo(url, run); console.error(`[ok] 《${info.title}》| ${info.channel} | ${info.duration}`);
  let body = ""; let source = "";
  if (!options.asr) { const got = trySubtitles(url, options.lang ? options.lang.split(",").map((item) => item.trim()).filter(Boolean) : DEFAULT_LANGUAGES, run); if (got) { body = got.text; source = `字幕 ${got.tag}`; } }
  if (!body) { const result = runAsr(url, options.model, run); body = result.text; source = `本地 ASR（${result.backend}，可能有识别误差）`; }
  if (!body?.trim()) { console.error("[错误] 未获得任何文本内容"); return 3; } const content = buildMarkdown(info, body, source);
  if (options.stdout) { process.stdout.write(content); return 0; }
  let output;
  if (options.out) output = resolve(expandHome(options.out));
  else { let vault; try { vault = findVault({ hint: fileURLToPath(import.meta.url), explicit: options.vault }); } catch (error) { if (!(error instanceof VaultNotFoundError)) throw error; console.error(`[错误] ${error.message}`); return 2; } output = join(vault, "raw", `yt-${info.id}-${sanitize(info.title)}.md`); }
  mkdirSync(dirname(output), { recursive: true }); writeFileSync(output, content, "utf8"); console.error(`[ok] 已写入 ${output}`); console.log(output); return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) { try { process.exitCode = main(); } catch (error) { console.error(`[错误] ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; } }
