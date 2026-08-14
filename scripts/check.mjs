#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { walkFiles } from "../lib/fs.mjs";

const repository = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const files = walkFiles(repository, (path) => path.endsWith(".mjs") && !path.includes("/node_modules/"));

for (const file of files) {
  const result = spawnSync(process.execPath, ["--check", file], { encoding: "utf8" });
  if (result.status !== 0) {
    process.stderr.write(result.stderr || result.stdout || `语法检查失败: ${file}\n`);
    process.exitCode = 1;
  }
}

if (!process.exitCode) console.log(`Checked ${files.length} Node files.`);
