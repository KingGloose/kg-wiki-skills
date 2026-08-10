#!/usr/bin/env python3
"""检查各 SKILL.md 是否可被 Agent 发现，且命令能否被正确解析。

为什么需要这个（真实故障复盘）：
  文档曾写死 `cd kg-wiki-skills && source .venv/bin/activate`。
  但 skill 是通过软链被发现的（软链名叫 kg，不叫 kg-wiki-skills），
  且 AI 的工作目录是用户项目而非仓库目录 —— 于是 cd 失败，
  AI 误诊成"环境没装"，准备重装一遍。

  Agent Skills 规范的做法是：文档用**相对 SKILL.md 的路径**，
  AI 按已知规则解析成绝对路径。这样不依赖任何外部命名。

本脚本就查"文档里有没有 AI 解析不了的路径"。只读，不改文件。

用法:
  python3 lint_docs.py            # 人类可读
  python3 lint_docs.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# 仓库名硬编码 —— 依赖外部目录叫什么，是最容易踩的坑
REPO_NAME_RE = re.compile(r'\bcd\s+["\']?kg-wiki-skills\b')
# 未定义就用的 shell 变量（文档里出现 $KG 但没说它是什么）
UNDEF_VAR_RE = re.compile(r'\$\{?([A-Z][A-Z_]{1,})\}?')
# 绝对路径写死到某个用户目录
USER_PATH_RE = re.compile(r'/(?:Users|home)/[a-zA-Z0-9_.-]+/')
# 依赖全局软链名的路径
LINK_PATH_RE = re.compile(r'~/\.(?:agents|claude)/skills/[a-zA-Z0-9_-]+/')
# 假设 skill 仓库嵌在知识库里的相对输出路径
VAULT_LAYOUT_REL_RE = re.compile(r'(?:^|\s)(?:\.\./)+(?:raw|wiki|assets)(?:/|\s|$)')

KNOWN_VARS = {"HOME", "PATH", "PWD", "SHELL", "USER", "LOCALAPPDATA",
              "KG_VAULT", "VIRTUAL_ENV", "WSL_DISTRO_NAME", "WIN_IP",
              "BASH_SOURCE", "OSTYPE", "PYTHONPATH", "SESSDATA"}


def bash_blocks(text: str) -> list[tuple[int, str]]:
    """抽出 ```bash 代码块，返回 (起始行号, 内容)。"""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if re.match(r'^\s*```(?:bash|sh|shell|console)\s*$', lines[i]):
            start, i = i + 1, i + 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            out.append((start + 1, "\n".join(buf)))
        i += 1
    return out


def check_skill(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(REPO))
    issues: list[dict] = []

    if not text.startswith("---\n"):
        issues.append({
            "file": rel, "line": 1, "kind": "missing-frontmatter",
            "severity": "error", "text": text.splitlines()[0] if text else "",
            "why": "缺少 YAML frontmatter，Pi/Codex 不会发现这个 skill",
            "fix": "在文件开头添加含 name 和 description 的 YAML frontmatter",
        })
    else:
        end = text.find("\n---\n", 4)
        frontmatter = text[4:end] if end >= 0 else ""
        name = re.search(r"^name:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
        description = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
        if end < 0 or not name or not description:
            issues.append({
                "file": rel, "line": 1, "kind": "invalid-frontmatter",
                "severity": "error", "text": "YAML frontmatter",
                "why": "frontmatter 必须完整包含非空的 name 和 description",
                "fix": "按 Agent Skills 规范补全 name 和 description",
            })
        elif name.group(1) != path.parent.name:
            issues.append({
                "file": rel, "line": 2, "kind": "skill-name-mismatch",
                "severity": "error", "text": name.group(1),
                "why": f"skill 名称与目录名 {path.parent.name} 不一致",
                "fix": f"把 name 改为 {path.parent.name}",
            })

    # 文档正文里对变量的说明（用于判断 $VAR 有没有被解释）
    explained = set(re.findall(r'`\$\{?([A-Z][A-Z_]+)\}?`\s*[=＝]', text))
    explained |= set(re.findall(r'\$\{?([A-Z][A-Z_]+)\}?\s*(?:=|指|表示|就是)', text))

    for lineno, block in bash_blocks(text):
        for off, line in enumerate(block.split("\n")):
            ln, stripped = lineno + off, line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if REPO_NAME_RE.search(stripped):
                issues.append({
                    "file": rel, "line": ln, "kind": "hardcoded-repo-name",
                    "severity": "error", "text": stripped,
                    "why": "写死仓库目录名。skill 通过软链被发现时目录名可能不同，"
                           "且 AI 的工作目录是用户项目 —— 这条 cd 会失败",
                    "fix": "改用相对 SKILL.md 的路径，如 source ../.venv/bin/activate",
                })

            for var in UNDEF_VAR_RE.findall(stripped):
                if var not in KNOWN_VARS and var not in explained:
                    issues.append({
                        "file": rel, "line": ln, "kind": "undefined-var",
                        "severity": "error", "text": stripped,
                        "why": f"用了 ${var} 但文档没说它是什么，AI 无法解析",
                        "fix": f"改用相对路径，或在文档里明确定义 ${var}",
                    })

            if m := USER_PATH_RE.search(stripped):
                issues.append({
                    "file": rel, "line": ln, "kind": "absolute-user-path",
                    "severity": "error", "text": stripped,
                    "why": f"写死了某台机器的用户目录（{m.group(0)}）",
                    "fix": "改用相对路径或 ~ ",
                })

            if m := LINK_PATH_RE.search(stripped):
                issues.append({
                    "file": rel, "line": ln, "kind": "depends-on-link-name",
                    "severity": "warn", "text": stripped,
                    "why": f"依赖全局软链名（{m.group(0)}）。用户软链可能起别的名字",
                    "fix": "优先用相对 SKILL.md 的路径；确需示例时说明这只是示例",
                })

            if m := VAULT_LAYOUT_REL_RE.search(stripped):
                issues.append({
                    "file": rel, "line": ln, "kind": "assumes-skills-inside-vault",
                    "severity": "error", "text": stripped,
                    "why": f"相对输出路径（{m.group(0).strip()}）假设 skill 仓库位于知识库内部，"
                           "独立部署或软链调用时会写错位置",
                    "fix": "使用 vault 解析后的绝对路径，或省略 --out 让脚本写入已解析的库",
                })

    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="检查 SKILL.md 的 frontmatter 和路径")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    skills = sorted(REPO.glob("kg-*/SKILL.md"))
    all_issues = [i for p in skills for i in check_skill(p)]
    errors = [i for i in all_issues if i["severity"] == "error"]
    warns = [i for i in all_issues if i["severity"] == "warn"]

    if args.json:
        print(json.dumps({"skills_checked": len(skills), "issues": all_issues,
                          "errors": len(errors), "warnings": len(warns)},
                         ensure_ascii=False, indent=2))
        return 1 if errors else 0

    print(f"# SKILL.md 发现与路径检查\n\n检查了 {len(skills)} 个 skill")
    if not all_issues:
        print("\n✅ 没有发现问题 —— 所有 skill 都可发现，命令也能被 AI 正确解析。")
        print("\n（规范做法：文档用相对 SKILL.md 的路径，AI 会解析成绝对路径。")
        print("  这样不依赖软链名、不依赖工作目录。）")
        return 0

    for group, title in ((errors, "❌ 错误（AI 会执行失败）"), (warns, "⚠️  警告")):
        if not group:
            continue
        print(f"\n## {title}\n")
        for i in group:
            print(f"  {i['file']}:{i['line']}  [{i['kind']}]")
            print(f"    命令: {i['text']}")
            print(f"    原因: {i['why']}")
            print(f"    修法: {i['fix']}\n")

    print(f"合计 {len(errors)} 个错误、{len(warns)} 个警告")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
