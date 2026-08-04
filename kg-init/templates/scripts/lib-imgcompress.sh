#!/usr/bin/env bash
# 图片压缩公共库：把单张图片就地转成 WebP。
# 被 compress-images.sh(批量迁移) 和 hooks/pre-commit(日常增量) 共用，
# 保证两条路径的压缩策略永远一致。
#
# 策略（实测数据见 README「为什么统一 WebP」）：
#   静态图  -> cwebp  -q WEBP_QUALITY，宽度上限 MAX_WIDTH
#   动图GIF -> gif2webp 保留动画
#   兜底    -> magick 转换（应对 BMP 伪装成 .jpg 等脏数据）
# 安全网：压完体积没变小就保留原图，绝不为了统一格式反而变大。

set -uo pipefail

WEBP_QUALITY="${WEBP_QUALITY:-82}"
MAX_WIDTH="${MAX_WIDTH:-1600}"
GIF_QUALITY="${GIF_QUALITY:-75}"
GIF_MAX_WIDTH="${GIF_MAX_WIDTH:-1000}"

# 判断是否动图（多帧）。gif2webp 只该用在真动图上，
# 单帧 GIF 走静态 cwebp 更小。
img_is_animated() {
  local f=$1
  local frames
  frames=$(magick identify -format '%n\n' "$f" 2>/dev/null | head -1)
  [[ ${frames:-1} =~ ^[0-9]+$ ]] && (( frames > 1 ))
}

# compress_one <源文件> <目标.webp>
# 成功且更小 -> 写入目标, 返回 0
# 压不动/失败 -> 不产出目标, 返回 1（调用方保留原图）
compress_one() {
  local src=$1 dst=$2
  # 临时文件必须带 .webp 后缀：magick 靠扩展名推断输出格式，
  # 用 .tmp1234 这种它认不出来会直接失败。
  local tmp="${dst%.webp}.tmp$$.webp"
  local orig_size new_size mime

  orig_size=$(stat -f '%z' "$src" 2>/dev/null) || return 1
  mime=$(file --mime-type -b "$src" 2>/dev/null)

  if [[ $mime == image/gif ]] && img_is_animated "$src"; then
    # 动图：-lossy 是关键，gif2webp 默认逐帧无损，同一张图 9.6MB vs 2.1MB
    local gtmp="${dst%.webp}.g$$.gif"
    if magick "$src" -coalesce -resize "${GIF_MAX_WIDTH}x>" -layers optimize "$gtmp" 2>/dev/null; then
      gif2webp -lossy -q "$GIF_QUALITY" -m 6 -quiet "$gtmp" -o "$tmp" 2>/dev/null
      rm -f "$gtmp"
    fi
    # magick 那步失败就直接拿原 GIF 试一次
    [[ -s $tmp ]] || gif2webp -lossy -q "$GIF_QUALITY" -m 6 -quiet "$src" -o "$tmp" 2>/dev/null
  else
    # 静态图：cwebp 主力
    cwebp -q "$WEBP_QUALITY" -resize "$MAX_WIDTH" 0 -quiet "$src" -o "$tmp" 2>/dev/null
    # cwebp 读不了的脏数据（如 BMP 伪装 .jpg）交给 magick 兜底，
    # webp: 前缀显式指定格式，不依赖扩展名推断
    if [[ ! -s $tmp ]]; then
      magick "$src" -resize "${MAX_WIDTH}x>" -quality "$WEBP_QUALITY" -strip "webp:$tmp" 2>/dev/null
    fi
  fi

  if [[ ! -s $tmp ]]; then
    rm -f "$tmp"
    return 1
  fi

  new_size=$(stat -f '%z' "$tmp" 2>/dev/null || echo 0)
  # 安全网：没省下来就放弃
  if (( new_size == 0 || new_size >= orig_size )); then
    rm -f "$tmp"
    return 1
  fi

  mv -f "$tmp" "$dst"
  return 0
}

human() {
  awk -v b="${1:-0}" 'BEGIN{
    split("B KB MB GB", u, " "); i=1
    while (b >= 1024 && i < 4) { b /= 1024; i++ }
    printf (i==1 ? "%d %s" : "%.1f %s"), b, u[i]
  }'
}
