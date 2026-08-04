#!/usr/bin/env bash
# 新机器 clone 之后跑一次，装好图片自动压缩 hook。
#
# 为什么需要这一步：git 不追踪 .git/hooks/，hook 无法随 clone 传播。
# 所以 hook 脚本作为普通文件放在 scripts/hooks/ 提交进仓库，
# 这里只是把 core.hooksPath 指过去。每台新机器跑一次即可。

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/* scripts/*.sh 2>/dev/null || true
echo "已设置 core.hooksPath = scripts/hooks"

echo
echo "检查图片压缩依赖:"
missing=()
for bin in cwebp gif2webp magick python3; do
  if command -v "$bin" >/dev/null; then
    printf '  %-10s OK\n' "$bin"
  else
    printf '  %-10s 缺失\n' "$bin"
    missing+=("$bin")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo
  echo "安装缺失依赖: brew install webp imagemagick"
  echo "(cwebp 和 gif2webp 都在 webp 包里)"
  exit 1
fi

echo
echo "就绪。以后提交时新增图片会自动压成 WebP。"
