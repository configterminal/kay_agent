#!/usr/bin/env python3
"""
课程视频 → 带时间戳 Markdown 逐字稿（faster-whisper，本地 GPU）。

用法（仓库根目录 f:\\agent）:
  python skills/course-transcribe/scripts/transcribe_video.py --dry-run
  python skills/course-transcribe/scripts/transcribe_video.py --course CAREER201
  python skills/course-transcribe/scripts/transcribe_video.py --model large-v3 --language zh
  python skills/course-transcribe/scripts/transcribe_video.py --force

输出：每个 .mp4 旁生成同 stem 的 .md（一视频一文件，含 [M:SS] / [H:MM:SS] 行）。
建议先按 skills/course-resource-rename 规范改名，再转写。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from faster_whisper import WhisperModel
except ImportError:
    sys.exit("请先安装: pip install faster-whisper --target f:\\jupyter")

from auto_fix_rules import apply_auto_fix

# ── 默认配置（与 SKILL.md 一致）──────────────────────────
DEFAULT_MODEL = "medium"
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE = "float16"
MODEL_CACHE = Path("F:/agent/.cache/whisper")
# ─────────────────────────────────────────────────────────


def find_mp4_files(base: Path, course_filter: str | None = None) -> list[Path]:
    """列出 base 下全部 .mp4，可按课程路径子串过滤（如 CAREER201）。"""
    files: list[Path] = []
    for root, _dirs, filenames in os.walk(base):
        for fn in filenames:
            if fn.endswith(".mp4") and not fn.startswith("._"):
                fp = Path(root) / fn
                if course_filter and course_filter not in str(fp):
                    continue
                files.append(fp)
    return sorted(files)


def get_duration_seconds(mp4_path: Path) -> float:
    """ffprobe 取时长；失败返回 0。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def format_time(seconds: float) -> str:
    """≥1 小时 → H:MM:SS；否则 M:SS。"""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_markdown(mp4_stem: str, transcript: str) -> str:
    """
    生成供 RAG 使用的 Markdown：仅标题 + 时间戳正文。
    不写模型/语言/耗时等运维元信息（避免进索引噪声）。
    """
    title = mp4_stem.replace("_ev", "")
    body = transcript.strip()
    return f"# {title}\n\n{body}\n"


def transcribe_one(
    model: WhisperModel,
    mp4_path: Path,
    language: str | None = None,
) -> tuple[str, float]:
    """转写单个 mp4，返回 (带时间戳正文, 检测时长)。"""
    kwargs: dict = {
        "beam_size": 5,
        "vad_filter": True,
        "vad_parameters": dict(min_silence_duration_ms=500),
    }
    if language:
        kwargs["language"] = language

    segments, info = model.transcribe(str(mp4_path), **kwargs)

    lines: list[str] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        text = apply_auto_fix(text)
        lines.append(f"[{format_time(seg.start)}] {text}")

    return "\n".join(lines), info.duration


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="用 faster-whisper 转写课程视频为带时间戳 md")
    ap.add_argument("--dry-run", action="store_true", help="只列出视频，不转写")
    ap.add_argument("--course", type=str, default=None, help="课程路径子串过滤，如 CAREER201")
    ap.add_argument("--model", type=str, default=DEFAULT_MODEL, help="默认 medium；精度可选 large-v3")
    ap.add_argument("--language", type=str, default=None, help="强制语言，中文建议 zh")
    ap.add_argument("--device", type=str, default=DEFAULT_DEVICE)
    ap.add_argument("--compute", type=str, default=DEFAULT_COMPUTE)
    ap.add_argument(
        "--force",
        action="store_true",
        help="即使已有同名 .md 也重新转写",
    )
    args = ap.parse_args()

    # skills/course-transcribe/scripts → 仓库根
    repo = Path(__file__).resolve().parents[3]
    courses_root = repo / "resources" / "courses"
    if not courses_root.is_dir():
        sys.exit(f"courses 目录不存在: {courses_root}")

    files = find_mp4_files(courses_root, args.course)
    if not files:
        print("没有找到 .mp4 文件。")
        return

    print(f"找到 {len(files)} 个视频文件:")
    total_dur = 0.0
    for fp in files:
        dur = get_duration_seconds(fp)
        total_dur += dur
        print(f"  {fp.relative_to(repo)}  ({format_time(dur)})")
    print(f"总时长约: {format_time(total_dur)}")

    if args.dry_run:
        print("\n[dry-run] 不执行转写。")
        return

    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    # 只用 download_root，不改全局 HF_HOME（避免影响 BGE 等其它缓存）

    print(f"\n加载模型 {args.model} (device={args.device}, compute={args.compute}) ...")
    t0 = time.time()
    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute,
        download_root=str(MODEL_CACHE),
    )
    print(f"模型就绪 ({time.time() - t0:.1f}s)")

    print(f"\n开始转写 {len(files)} 个文件...\n")
    ok = fail = skip = 0

    for i, mp4_path in enumerate(files, 1):
        rel = mp4_path.relative_to(repo)
        out_md = mp4_path.with_suffix(".md")

        if out_md.exists() and not args.force:
            print(f"  [{i}/{len(files)}] SKIP (已有 .md): {rel}")
            skip += 1
            continue

        try:
            dur = get_duration_seconds(mp4_path)
            print(
                f"  [{i}/{len(files)}] 转写中: {rel}  ({format_time(dur)}) ...",
                flush=True,
            )
            t1 = time.time()
            transcript, _detected = transcribe_one(model, mp4_path, args.language)
            elapsed = time.time() - t1
            speed = dur / elapsed if elapsed > 0 and dur > 0 else 0

            out_md.write_text(
                format_markdown(mp4_path.stem, transcript),
                encoding="utf-8",
            )
            print(
                f"        -> {out_md.name}  "
                f"(速度: {speed:.1f}x, 耗时: {format_time(elapsed)})"
            )
            ok += 1
        except Exception as e:
            print(f"        -> 失败: {e}")
            fail += 1

    print(f"\n完成: {ok} 成功, {skip} 跳过, {fail} 失败")


if __name__ == "__main__":
    main()
