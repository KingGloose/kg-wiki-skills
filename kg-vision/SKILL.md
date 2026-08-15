---
name: kg-vision
description: 图片识别（多模态）。当前主模型（deepseek）没有视觉能力，遇到需要看图/OCR/识图/视频画面分析时，用 vision.mjs 把图片转成文字描述。当用户发图片、让识别图片或截图内容、OCR、看视频画面、理解图片场景时使用。
---

# kg-vision · 图片识别

## 何时用

主模型（deepseek）**没有视觉能力**。遇到这些情况就用本 skill：

- 用户发图片让你看 / 识别图片内容
- OCR 截图、识别文字
- 视频画面分析（配合 kg-bilibili 下载视频后抽帧）
- 需要理解图片场景（封面、截图、图表、扫码内容）

**流程**：先用 `vision.mjs` 把图片转成文字描述，再用文字继续处理。

## 用法

```bash
node ~/.agents/skills/kg-wiki-skills/kg-vision/scripts/vision.mjs <图片路径> [问题]
```

- `<图片路径>`：本地图片（jpg/png/webp/gif）
- `[问题]`：可选，不传默认「描述这张图片的内容，尽量详细」
- stdout 输出图片的文字描述

## 配置

凭据在 `~/.piko-config/credentials/qwen.json`：

```json
{
  "api_key": "sk-...",
  "base_url": "https://llm-xxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
  "model": "qwen3.7-plus"
}
```

阿里云百炼千问（视觉 + 文本，OpenAI 兼容接口）。

## 边界

- **一次一张图**，多图分开识别
- 识别结果可能有误差（复杂图表/小字/模糊图），不确定就说不确定，别装
- 视频画面：先 `ffmpeg -ss <秒数> -i 视频 -frames:v 1 抽帧` 抽成图片再识别
