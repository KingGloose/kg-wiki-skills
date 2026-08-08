#!/usr/bin/env bash
# 批量把仓库里的图片压成 WebP，并输出「旧路径 -> 新路径」映射表供 fix-refs.py 改引用。
#
# 用法:
#   scripts/compress-images.sh [目标目录]        # 默认仓库根
#   DRY_RUN=1 scripts/compress-images.sh         # 只估算不落盘
#   JOBS=4 scripts/compress-images.sh            # 指定并行度
#
# 产出: .compress-map.tsv  (旧相对路径 \t 新相对路径)，仅含真正改了名的
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
REPO_ROOT=$PWD
source "$REPO_ROOT/scripts/lib-imgcompress.sh"

TARGET="${1:-$REPO_ROOT}"
JOBS="${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 4)}"
DRY_RUN="${DRY_RUN:-0}"
MAP_FILE="$REPO_ROOT/.compress-map.tsv"

for bin in cwebp gif2webp magick; do
  command -v "$bin" >/dev/null || { echo "缺少 ${bin}，先跑: brew install webp imagemagick" >&2; exit 1; }
done

echo "扫描图片: $TARGET"
LIST=$(mktemp); trap 'rm -f "$LIST"' EXIT
find "$TARGET" -type f \
  \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \
     -o -iname '*.gif' -o -iname '*.bmp' -o -iname '*.webp' \) \
  -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/.trash/*' \
  -print0 > "$LIST"

TOTAL=$(tr -cd '\0' < "$LIST" | wc -c | tr -d ' ')
echo "共 ${TOTAL} 张，并行度 ${JOBS}，质量 q${WEBP_QUALITY}，宽度上限 ${MAX_WIDTH}px"
[[ $DRY_RUN == 1 ]] && echo "(DRY_RUN 模式，不写入)"
echo

# 单张处理逻辑跑在子进程里，通过 NUL 分隔的结果行回传给主进程汇总。
# 结果行格式: <状态>\t<原字节>\t<新字节>\t<旧相对路径>\t<新相对路径>
process_one() {
  local src=$1
  local rel="${src#$REPO_ROOT/}"
  local dir base stem dst reldst orig new
  dir=$(dirname "$src"); base=$(basename "$src"); stem="${base%.*}"
  dst="$dir/$stem.webp"
  reldst="${dst#$REPO_ROOT/}"
  orig=$(stat -f '%z' "$src" 2>/dev/null || echo 0)
  if [[ $dst != "$src" ]]; then
    dst=$(unique_webp_path "$src")
    reldst="${dst#$REPO_ROOT/}"
  fi

  # 已是 webp 且不超宽的，尝试重压；压不动就跳过
  if [[ $DRY_RUN == 1 ]]; then
    local td t; td=$(mktemp -d); t="$td/preview.webp"
    if compress_one "$src" "$t"; then
      new=$(stat -f '%z' "$t"); rm -rf "$td"
      printf 'OK\t%s\t%s\t%s\t%s\0' "$orig" "$new" "$rel" "$reldst"
    else
      rm -rf "$td"
      printf 'SKIP\t%s\t%s\t%s\t%s\0' "$orig" "$orig" "$rel" "$rel"
    fi
    return
  fi

  if [[ $dst == "$src" ]]; then
    # 同名（本来就是 .webp）：原地重压，用临时文件避免自己覆盖自己
    local t="$src.re$$.webp"
    if compress_one "$src" "$t"; then
      new=$(stat -f '%z' "$t"); mv -f "$t" "$src"
      printf 'OK\t%s\t%s\t%s\t%s\0' "$orig" "$new" "$rel" "$rel"
    else
      rm -f "$t"
      printf 'SKIP\t%s\t%s\t%s\t%s\0' "$orig" "$orig" "$rel" "$rel"
    fi
    return
  fi

  if compress_one "$src" "$dst"; then
    new=$(stat -f '%z' "$dst")
    rm -f "$src"
    printf 'OK\t%s\t%s\t%s\t%s\0' "$orig" "$new" "$rel" "$reldst"
  else
    printf 'SKIP\t%s\t%s\t%s\t%s\0' "$orig" "$orig" "$rel" "$rel"
  fi
}
export -f process_one compress_one img_is_animated unique_webp_path
export REPO_ROOT DRY_RUN WEBP_QUALITY MAX_WIDTH GIF_QUALITY GIF_MAX_WIDTH

RESULTS=$(mktemp); trap 'rm -f "$LIST" "$RESULTS"' EXIT
xargs -0 -P "$JOBS" -I{} bash -c 'process_one "$@"' _ {} < "$LIST" > "$RESULTS"

python3 - "$RESULTS" "$MAP_FILE" "$DRY_RUN" <<'PY'
import sys, os
res, mapfile, dry = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
ok = skip = 0
orig_total = new_total = 0
rows = []
with open(res, 'rb') as f:
    for rec in f.read().split(b'\0'):
        if not rec.strip():
            continue
        parts = rec.decode('utf-8', 'surrogateescape').split('\t')
        if len(parts) != 5:
            continue
        status, o, n, old, new = parts
        orig_total += int(o)
        new_total += int(n)
        if status == 'OK':
            ok += 1
            if old != new:
                rows.append((old, new))
        else:
            skip += 1

def h(b):
    for u in ('B', 'KB', 'MB', 'GB'):
        if b < 1024 or u == 'GB':
            return f'{b:.1f} {u}'
        b /= 1024

if not dry:
    with open(mapfile, 'w', encoding='utf-8') as f:
        for old, new in rows:
            f.write(f'{old}\t{new}\n')

print(f'压缩成功 {ok} 张，跳过(压不动/失败) {skip} 张')
print(f'原始 {h(orig_total)}  ->  现在 {h(new_total)}', end='')
if orig_total:
    print(f'   (剩 {new_total*100/orig_total:.1f}%, 省 {h(orig_total-new_total)})')
else:
    print()
if not dry:
    print(f'改名映射 {len(rows)} 条 -> {mapfile}')
    print('下一步: python3 scripts/fix-refs.py')
PY
