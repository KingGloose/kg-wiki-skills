#!/usr/bin/env node
/**
 * 千问识图：把图片转成文字描述（OpenAI 兼容接口）。
 *
 * 用法：node vision.mjs <图片路径> [问题]
 *   - 图片路径：本地图片（jpg/png/webp/gif）
 *   - 问题（可选）：不传默认「描述这张图片的内容」
 *   - stdout 输出图片的文字描述
 *
 * 凭据：~/.piko-config/credentials/qwen.json（阿里云百炼 千问 qwen3.7-plus）
 */
import { readFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const CRED_FILE = join(homedir(), ".piko-config", "credentials", "qwen.json");

const imgPath = process.argv[2];
const question = process.argv[3] || "描述这张图片的内容，尽量详细。";

if (!imgPath || !existsSync(imgPath)) {
  console.error("用法：node vision.mjs <图片路径> [问题]");
  process.exit(1);
}
if (!existsSync(CRED_FILE)) {
  console.error(`找不到凭据：${CRED_FILE}（先在 qwen.json 里配 api_key）`);
  process.exit(1);
}

const cred = JSON.parse(readFileSync(CRED_FILE, "utf8"));
const b64 = readFileSync(imgPath).toString("base64");
const ext = imgPath.split(".").pop().toLowerCase();
const mime =
  ext === "png" ? "image/png" : ext === "gif" ? "image/gif" : ext === "webp" ? "image/webp" : "image/jpeg";

const res = await fetch(`${cred.base_url}/chat/completions`, {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${cred.api_key}` },
  body: JSON.stringify({
    model: cred.model || "qwen3.7-plus",
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: question },
          { type: "image_url", image_url: { url: `data:${mime};base64,${b64}` } },
        ],
      },
    ],
  }),
});

const d = await res.json();
const content = d?.choices?.[0]?.message?.content;
if (content) {
  console.log(content);
} else {
  console.error("识别失败:", JSON.stringify(d).slice(0, 300));
  process.exit(1);
}
