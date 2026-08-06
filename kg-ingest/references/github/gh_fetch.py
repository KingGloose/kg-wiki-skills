#!/usr/bin/env python3
"""GitHub 内容摄入：薄封装官方 `gh` CLI。

为什么包一层而不直接让 AI 敲 gh：
  · GitHub 直连不通，每条命令都要带 HTTPS_PROXY —— 集中处理掉
  · issue/PR 的正文加讨论要拼装成可读 Markdown，不是 gh 的职责
  · 落 raw/ 的命名和 frontmatter 要跟其他 kg-* 一致

为什么用 gh 而不是自己调 REST：
  官方 CLI，认证走 OAuth（不用手工建 token 也不用存密钥），
  分页、限流、错误处理它都管了。

用法：
  gh_fetch.py stars                       # 我 star 了什么
  gh_fetch.py issue <owner/repo>#<号>     # 单个 issue 全文+讨论
  gh_fetch.py mine                        # 我提的 issue / PR
  gh_fetch.py repo <owner/repo>           # 仓库概况 + README
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CN = timezone(timedelta(hours=8))
# GitHub 直连不通，走本地代理。允许用环境变量覆盖（换网络环境时）。
DEFAULT_PROXY = os.environ.get("KG_GH_PROXY", "http://127.0.0.1:7897")


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def gh(*args: str, timeout: int = 120) -> str:
    """跑 gh 并返回 stdout。自动注入代理。"""
    env = dict(os.environ)
    if DEFAULT_PROXY and not env.get("HTTPS_PROXY"):
        env["HTTPS_PROXY"] = DEFAULT_PROXY
        env["HTTP_PROXY"] = DEFAULT_PROXY
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=timeout, env=env, check=False)
    except FileNotFoundError:
        raise SystemExit("[错误] 找不到 gh。装：brew install gh，再 gh auth login")
    except subprocess.TimeoutExpired:
        raise SystemExit(f"[错误] gh 超时（{timeout}s）。检查代理 {DEFAULT_PROXY} 是否可用")
    if p.returncode:
        err = (p.stderr or "").strip()
        if "auth login" in err or "authentication" in err.lower():
            raise SystemExit("[错误] gh 未认证。跑：\n"
                             f"  HTTPS_PROXY={DEFAULT_PROXY} gh auth login")
        raise SystemExit(f"[错误] gh 失败（exit {p.returncode}）：{err[:300]}")
    return p.stdout


def now() -> str:
    return datetime.now(CN).strftime("%Y-%m-%d %H:%M")


def fm(title: str, source: str, **extra) -> list:
    """统一的 frontmatter，跟其他 kg-* skill 对齐。"""
    L = ["---", f"title: {title}", f"source: {source}", "platform: GitHub",
         f"fetched: {now()}"]
    for k, v in extra.items():
        if v not in (None, "", []):
            L.append(f"{k}: {v}")
    L += ["---", ""]
    return L


# ---------------------------------------------------------------- stars

def cmd_stars(args) -> str:
    raw = gh("api", "user/starred", "--paginate",
             "--jq", ".[] | {full_name, description, language, stargazers_count, "
                     "html_url, topics, pushed_at}")
    repos = [json.loads(l) for l in raw.splitlines() if l.strip()]
    if args.language:
        want = args.language.lower()
        repos = [r for r in repos if (r.get("language") or "").lower() == want]
    repos.sort(key=lambda r: r.get("stargazers_count") or 0, reverse=True)

    L = fm(f"GitHub Star 清单（{len(repos)} 个）", "https://github.com/?tab=stars",
           count=len(repos))
    L += [f"# GitHub Star（{len(repos)} 个）", ""]

    by_lang: dict = {}
    for r in repos:
        by_lang.setdefault(r.get("language") or "其他", []).append(r)

    L += ["## 语言分布", ""]
    for lang, rs in sorted(by_lang.items(), key=lambda kv: -len(kv[1])):
        L.append(f"- {lang} · {len(rs)}")
    L.append("")

    for lang, rs in sorted(by_lang.items(), key=lambda kv: -len(kv[1])):
        L += [f"## {lang}", ""]
        for r in rs:
            desc = (r.get("description") or "").strip()
            L.append(f"- **[{r['full_name']}]({r['html_url']})** "
                     f"★{r.get('stargazers_count', 0)}"
                     + (f" — {desc}" if desc else ""))
            if r.get("topics"):
                L.append(f"  - `{'` `'.join(r['topics'][:8])}`")
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- issue

def cmd_issue(args) -> str:
    spec = args.target.replace("#", "/issues/") if "#" in args.target else args.target
    if "/issues/" not in spec and "/pull/" not in spec:
        raise SystemExit("[错误] 格式：owner/repo#123 或 owner/repo/issues/123")
    repo, _, num = spec.partition("/issues/")
    if not num:
        repo, _, num = spec.partition("/pull/")

    meta = json.loads(gh("api", f"repos/{repo}/issues/{num}"))
    L = fm(meta.get("title", ""), meta.get("html_url", ""),
           repo=repo, number=num, state=meta.get("state"),
           author=(meta.get("user") or {}).get("login"),
           created=(meta.get("created_at") or "")[:10],
           comments=meta.get("comments", 0))
    L += [f"# {meta.get('title','')}", "",
          f"> {repo} #{num} · {meta.get('state')} · "
          f"@{(meta.get('user') or {}).get('login')} · "
          f"{(meta.get('created_at') or '')[:10]}",
          f"> {meta.get('html_url','')}", ""]
    if meta.get("labels"):
        L += ["**标签**：" + " ".join(f"`{l['name']}`" for l in meta["labels"]), ""]
    L += ["## 正文", "", (meta.get("body") or "_（空）_").strip(), ""]

    if meta.get("comments"):
        cs = json.loads(gh("api", f"repos/{repo}/issues/{num}/comments",
                           "--paginate"))
        L += [f"## 讨论（{len(cs)} 条）", ""]
        for c in cs:
            who = (c.get("user") or {}).get("login", "?")
            when = (c.get("created_at") or "")[:10]
            L += [f"### @{who} · {when}", "",
                  (c.get("body") or "").strip(), ""]
    return "\n".join(L)


# ---------------------------------------------------------------- mine

def cmd_mine(args) -> str:
    out = gh("search", "issues", "--author=@me", f"--limit={args.limit}",
             "--json", "repository,title,state,url,createdAt,isPullRequest,body")
    items = json.loads(out)
    L = fm(f"我提的 issue / PR（{len(items)} 条）",
           "https://github.com/issues?q=author%3A%40me", count=len(items))
    L += [f"# 我提的 issue / PR（{len(items)} 条）", "",
          "> 这些是你自己写下的问题和判断，比 star 更能反映你实际踩过什么。", ""]
    for it in items:
        kind = "PR" if it.get("isPullRequest") else "issue"
        L += [f"## [{it['repository']['nameWithOwner']}]({it['url']}) · {kind}",
              "",
              f"**{it['title']}**",
              "",
              f"> {it.get('state')} · {(it.get('createdAt') or '')[:10]}", ""]
        body = (it.get("body") or "").strip()
        if body:
            L += [body[:1200] + ("…" if len(body) > 1200 else ""), ""]
    return "\n".join(L)


# ---------------------------------------------------------------- repo

def cmd_repo(args) -> str:
    r = json.loads(gh("api", f"repos/{args.target}"))
    L = fm(r.get("full_name", ""), r.get("html_url", ""),
           stars=r.get("stargazers_count"), language=r.get("language"),
           license=((r.get("license") or {}) or {}).get("spdx_id"),
           pushed=(r.get("pushed_at") or "")[:10])
    L += [f"# {r.get('full_name','')}", "",
          f"> ★{r.get('stargazers_count',0)} · {r.get('language') or '-'} · "
          f"最后推送 {(r.get('pushed_at') or '')[:10]}",
          f"> {r.get('html_url','')}", "",
          (r.get("description") or "").strip(), ""]
    if r.get("topics"):
        L += ["**Topics**：" + " ".join(f"`{t}`" for t in r["topics"]), ""]
    try:
        readme = gh("api", f"repos/{args.target}/readme",
                    "-H", "Accept: application/vnd.github.raw")
        L += ["## README", "", readme.strip(), ""]
    except SystemExit:
        L += ["_（没取到 README）_", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="GitHub 内容摄入（封装 gh CLI）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stars", help="我 star 的仓库")
    p.add_argument("--language", help="只看某语言")
    p.set_defaults(fn=cmd_stars)

    p = sub.add_parser("issue", help="单个 issue/PR 全文 + 讨论")
    p.add_argument("target", help="owner/repo#123")
    p.set_defaults(fn=cmd_issue)

    p = sub.add_parser("mine", help="我提的 issue / PR")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_mine)

    p = sub.add_parser("repo", help="仓库概况 + README")
    p.add_argument("target", help="owner/repo")
    p.set_defaults(fn=cmd_repo)

    for s in (sub.choices.values()):
        s.add_argument("--out", default=None, help="输出 md；不给则打到 stdout")

    args = ap.parse_args()
    md = args.fn(args)
    if args.out:
        pth = Path(args.out)
        pth.parent.mkdir(parents=True, exist_ok=True)
        pth.write_text(md, encoding="utf-8")
        eprint(f"[ok] 写入 {pth}（{len(md)} 字符）")
    else:
        print(md)


if __name__ == "__main__":
    main()
