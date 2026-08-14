# 从 Chrome 历史/书签找内容

用 Node 脚本只读本机 Chrome 的 `Bookmarks` JSON 和 `History` SQLite，不读 cookie，不上传数据。历史库先复制到临时目录再查询，避免和运行中的 Chrome 锁冲突。

## 命令

```bash
bin/kg-node kg-browser/scripts/find-history.mjs "LLM Wiki"
bin/kg-node kg-browser/scripts/find-history.mjs --keywords 知乎 zhihu 知识库
bin/kg-node kg-browser/scripts/find-history.mjs --keywords AI Agent --articles-only
bin/kg-node kg-browser/scripts/find-history.mjs --keywords 播客 --days 30 --articles-only
```

可选参数：

- `--limit N`：最多返回数，默认 10。
- `--days N`：只保留最近 N 天访问过的历史项；无访问时间的书签仍保留。
- `--articles-only`：过滤搜索页、登录页和站点首页。
- `--chrome-home <path>`：显式指定 Chrome 用户数据目录。
- `--pretty`：缩进 JSON。

## 使用准则

1. AI 根据用户语义主动扩展中英文、同义词和域名片段；脚本只做通用分词，不内置同义词表。
2. 找具体内容时默认使用 `--articles-only`。
3. 候选标题相似时让用户确认，不自行决定。
4. 结果为空时依次缩短关键词、改搜域名词、切换中英文；仍找不到就请用户提供更多线索。

输出 JSON 候选项包含 `title` / `url` / `source` / `profile` / `last_visit_time` / `bookmark_path` / `match_score`。
