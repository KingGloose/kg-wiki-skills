"""图片压缩：把图片统一压成 WebP，控制知识库体积。

**为什么沉在底层库**：所有会往库里落图的上层 skill（kg-wechat 下载公众号配图、
kg-zhihu 抓专栏图、kg-bilibili 存封面、kg-doc 提取 PDF 插图）都需要这一步。
按 AGENTS.md「转换能力沉在底层库复用」，压缩策略只在这里实现一份。

**为什么统一 WebP**（实测对照，统一宽度上限 1600px）:

| 格式 | 样本 | 原始 | 同格式压缩 | WebP |
|------|------|------|-----------|------|
| PNG  | 201 张 | 26.1 MB | 9.1 MB (35.0%) | 9.3 MB (35.6%) |
| JPEG | 145 张 | 24.9 MB | 12.1 MB (48.6%) | **7.0 MB (28.0%)** |
| GIF  |  49 张 | 43.4 MB | 34.2 MB (78.9%) | **12.0 MB (27.6%)** |

PNG 上 `pngquant + oxipng` 和 WebP 基本持平，JPEG / GIF 上 WebP 大幅领先。
统一 WebP 换来格式单一、工具链简单、引用规则一致。

依赖外部 CLI（`brew install webp imagemagick`）：
  cwebp     静态图主力
  gif2webp  动图（**必须带 -lossy**，默认逐帧无损，同一张图 9.6MB vs 2.1MB）
  magick    读取帧数 + 兜底转换（应对 BMP 伪装成 .jpg 这类脏数据）
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .types import MediaToTextError

# 默认参数。调用方可按需覆盖，知识库侧的 shell 脚本用的是同一组值。
WEBP_QUALITY = 82
MAX_WIDTH = 1600
GIF_QUALITY = 75
GIF_MAX_WIDTH = 1000

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


class ImageCompressError(MediaToTextError):
    """压缩失败（缺依赖或源文件不可读）。"""


@dataclass
class CompressResult:
    """单张图片的压缩结果。

    path       : 最终文件路径（成功时是新的 .webp；跳过时仍是原路径）
    original   : 原始字节数
    compressed : 压缩后字节数（跳过时等于 original）
    changed    : 是否真的替换了文件
    reason     : 跳过原因（changed=False 时有值）
    """

    path: Path
    original: int
    compressed: int
    changed: bool
    reason: str = ""

    @property
    def saved(self) -> int:
        return self.original - self.compressed

    @property
    def ratio(self) -> float:
        """压缩后占原始的比例，0.35 表示压到 35%。"""
        return self.compressed / self.original if self.original else 1.0


def _which(name: str) -> str | None:
    return shutil.which(name)


def check_deps() -> list[str]:
    """返回缺失的 CLI 名单，空列表表示齐全。"""
    return [b for b in ("cwebp", "gif2webp", "magick") if not _which(b)]


def _run(cmd: list[str]) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _frame_count(src: Path) -> int:
    """帧数。用于区分真动图和单帧 GIF——单帧走静态 cwebp 更小。"""
    try:
        proc = subprocess.run(
            ["magick", "identify", "-format", "%n\n", str(src)],
            capture_output=True, timeout=60, text=True,
        )
        first = proc.stdout.strip().splitlines()
        return int(first[0]) if first and first[0].isdigit() else 1
    except (OSError, subprocess.SubprocessError, ValueError):
        return 1


def _is_animated(src: Path) -> bool:
    try:
        head = src.open("rb").read(6)
    except OSError:
        return False
    if not head.startswith((b"GIF87a", b"GIF89a")):
        return False
    return _frame_count(src) > 1


def compress_image(
    src: str | os.PathLike,
    *,
    dest: str | os.PathLike | None = None,
    quality: int = WEBP_QUALITY,
    max_width: int = MAX_WIDTH,
    gif_quality: int = GIF_QUALITY,
    gif_max_width: int = GIF_MAX_WIDTH,
    keep_original: bool = False,
) -> CompressResult:
    """把单张图片压成 WebP。

    src           源文件
    dest          目标路径，默认同目录同名换 .webp
    keep_original True 则保留源文件（默认删掉，因为引用已改指向新文件）

    压完体积没变小时**保留原图**并返回 changed=False——小图转 WebP 常因头部
    开销反而变大，为了统一格式而让库变大是本末倒置。
    """
    src = Path(src)
    if not src.is_file():
        raise ImageCompressError(f"源文件不存在: {src}")

    missing = check_deps()
    if missing:
        raise ImageCompressError(
            f"缺少 CLI: {', '.join(missing)}。装: brew install webp imagemagick"
        )

    original = src.stat().st_size
    target = Path(dest) if dest else src.with_suffix(".webp")
    # 临时文件必须带 .webp 后缀：magick 靠扩展名推断输出格式，
    # 用 .tmp1234 这种它认不出来会直接失败。
    tmp = target.with_name(f"{target.stem}.tmp{os.getpid()}.webp")

    try:
        if _is_animated(src):
            # 动图：magick 先统一缩放（gif2webp 自身不支持 resize），再 gif2webp
            gtmp = target.with_name(f"{target.stem}.g{os.getpid()}.gif")
            ok = _run([
                "magick", str(src), "-coalesce",
                "-resize", f"{gif_max_width}x>", "-layers", "optimize", str(gtmp),
            ])
            if ok and gtmp.is_file():
                # -lossy 是关键，默认逐帧无损几乎不压缩
                _run(["gif2webp", "-lossy", "-q", str(gif_quality),
                      "-m", "6", "-quiet", str(gtmp), "-o", str(tmp)])
                gtmp.unlink(missing_ok=True)
            if not tmp.is_file() or tmp.stat().st_size == 0:
                _run(["gif2webp", "-lossy", "-q", str(gif_quality),
                      "-m", "6", "-quiet", str(src), "-o", str(tmp)])
        else:
            _run(["cwebp", "-q", str(quality), "-resize", str(max_width), "0",
                  "-quiet", str(src), "-o", str(tmp)])
            if not tmp.is_file() or tmp.stat().st_size == 0:
                # cwebp 读不了的脏数据交给 magick；webp: 前缀显式指定格式
                _run(["magick", str(src), "-resize", f"{max_width}x>",
                      "-quality", str(quality), "-strip", f"webp:{tmp}"])

        if not tmp.is_file() or tmp.stat().st_size == 0:
            return CompressResult(src, original, original, False, "转换失败")

        compressed = tmp.stat().st_size
        if compressed >= original:
            return CompressResult(src, original, original, False, "压完反而更大")

        if target.exists() and target != src:
            return CompressResult(src, original, original, False, f"目标已存在: {target.name}")

        tmp.replace(target)
        if not keep_original and src != target:
            src.unlink(missing_ok=True)
        return CompressResult(target, original, compressed, True)
    finally:
        tmp.unlink(missing_ok=True)


def compress_dir(
    directory: str | os.PathLike,
    *,
    recursive: bool = True,
    **kwargs,
) -> list[CompressResult]:
    """批量压缩目录下的图片。kwargs 透传给 compress_image。

    上层 skill 下载完一批图后调一次即可，例如：
        results = compress_dir(assets_dir)
        renames = {r.path.name: ... for r in results if r.changed}
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ImageCompressError(f"目录不存在: {directory}")

    pattern = "**/*" if recursive else "*"
    out: list[CompressResult] = []
    for p in sorted(directory.glob(pattern)):
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            try:
                out.append(compress_image(p, **kwargs))
            except ImageCompressError:
                out.append(CompressResult(p, p.stat().st_size, p.stat().st_size,
                                          False, "压缩异常"))
    return out


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def summarize(results: list[CompressResult]) -> str:
    """一行摘要，供上层 skill 打给用户看。"""
    changed = [r for r in results if r.changed]
    orig = sum(r.original for r in results)
    now = sum(r.compressed for r in results)
    if not results:
        return "没有图片需要压缩"
    pct = f"，剩 {now * 100 / orig:.1f}%" if orig else ""
    return (f"压缩 {len(changed)}/{len(results)} 张："
            f"{human_size(orig)} -> {human_size(now)}{pct}")
