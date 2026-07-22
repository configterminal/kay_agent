#!/usr/bin/env python3
"""
Video → text transcription using faster-whisper (local GPU).

Usage:
  python transcribe_video.py                          # transcribe ALL mp4 under courses/
  python transcribe_video.py --dry-run                # list files only
  python transcribe_video.py --course RAG101         # filter by course
  python transcribe_video.py --model medium           # use medium model (faster, less accurate)
  python transcribe_video.py --language zh            # force Chinese (default: auto-detect)

Model download location
  Models are cached to F:\agent\.cache\whisper (set via HF_HOME-adjacent env).
  First run downloads ~3 GB for large-v3, ~1.5 GB for medium.

Output
  Saves .txt alongside the .mp4, and a merged .md per chapter.
"""
import argparse, os, re, sys, time
from pathlib import Path

try:
    from faster_whisper import WhisperModel
except ImportError:
    sys.exit("请先安装: pip install faster-whisper --target f:\\jupyter")


# ── config ──────────────────────────────────────────────
DEFAULT_MODEL = "large-v3"        # best for Chinese
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE = "float16"       # RTX 5070 supports float16 well
MODEL_CACHE = Path("F:/agent/.cache/whisper")
# ─────────────────────────────────────────────────────────


def find_mp4_files(base: Path, course_filter: str | None = None) -> list[Path]:
    """Yield all .mp4 paths under base, optionally filtered by course dir name."""
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
    """Try to get video duration via ffprobe, fall back to 0 (unknown)."""
    import subprocess, json
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(mp4_path)],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


# ── ASR correction (reuse same logic as convert_docx.py) ──
# HIGH confidence → auto-fix
AUTO_FIX: list[tuple[str, str]] = [
    (r'(?<![a-zA-Z])rig(?![a-zA-Z])', "RAG"),
    (r'(?<![a-zA-Z])reg(?![a-zA-Z])', "RAG"),
    (r'(?<![a-zA-Z])ig(?![a-zA-Z])', "RAG"),
    (r'OPenAi', "OpenAI"),
    (r'deep\s*seek', "DeepSeek"),
    (r'\blamer\b', "LLaMA"),
    (r'LA\s*mer', "LLaMA"),
    (r'line\s*chain', "LangChain"),
    (r'p\s*touch', "PyTorch"),
    (r'g\s*radio', "Gradio"),
    (r'near\s*for\s*z', "Neo4j"),
    (r'jupiter\s*note', "Jupyter Notebook"),
    (r'jupiter', "Jupyter"),
    (r"ra'g", "RAG"),
    # Chinese ASR fixes — common Whisper mistakes
    (r'待遇模型', "大语言模型"),
    (r'大圆模型', "大语言模型"),
    (r'大元模型', "大语言模型"),
    (r'大于模型', "大语言模型"),
    (r'单元模型', "大语言模型"),
    (r'代元模型', "大语言模型"),
    (r'支持库', "知识库"),           # Whisper often hears 知识 as 支持
    (r'上下网', "上下文"),           # Whisper often hears 上下文 as 上下网
    (r'掐gpt', "ChatGPT"),
    (r'g\s*p\s*t', "GPT"),
    # Common Whisper Chinese errors in tech context
    (r'检索犯绝', "检索犯绝"),       # flag only — unclear original
]


def apply_fixes(text: str) -> str:
    for pattern, replacement in AUTO_FIX:
        text = re.sub(pattern, replacement, text)
    return text


def format_markdown(mp4_stem: str, transcript: str, model_name: str,
                    lang: str | None, video_dur: float, elapsed: float) -> str:
    """Format transcript as structured Markdown."""
    title = mp4_stem.replace("_ev", "")
    lines = [
        f"# {title}",
        "",
        f"> 模型: `{model_name}` | 语言: {lang or 'auto'} | "
        f"视频时长: {format_time(video_dur)} | 转写耗时: {format_time(elapsed)}",
        "",
        "---",
        "",
    ]
    lines.append(transcript)
    return "\n".join(lines) + "\n"


def transcribe_one(
    model: WhisperModel,
    mp4_path: Path,
    language: str | None = None,
) -> tuple[str, float]:
    """
    Transcribe a single mp4. Returns (transcript_text, duration_seconds).
    """
    transcribe_kwargs = {
        "beam_size": 5,
        "vad_filter": True,           # skip silence
        "vad_parameters": dict(
            min_silence_duration_ms=500,
        ),
    }
    if language:
        transcribe_kwargs["language"] = language

    segments, info = model.transcribe(str(mp4_path), **transcribe_kwargs)

    lines: list[str] = []
    for seg in segments:
        ts = format_time(seg.start)
        text = seg.text.strip()
        if text:
            # Apply auto-fixes
            text = apply_fixes(text)
            lines.append(f"[{ts}] {text}")

    transcript = "\n".join(lines)
    return transcript, info.duration


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe course videos with faster-whisper")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--course", type=str, default=None)
    ap.add_argument("--model", type=str, default=DEFAULT_MODEL)
    ap.add_argument("--language", type=str, default=None,
                    help="Force language code (e.g. zh, en, auto)")
    ap.add_argument("--device", type=str, default=DEFAULT_DEVICE)
    ap.add_argument("--compute", type=str, default=DEFAULT_COMPUTE)
    ap.add_argument("--force", action="store_true",
                    help="Re-transcribe even if .txt already exists")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent.parent.parent  # f:\agent
    courses_root = repo / "resources" / "courses"

    if not courses_root.is_dir():
        sys.exit(f"courses 目录不存在: {courses_root}")

    files = find_mp4_files(courses_root, args.course)
    if not files:
        print("没有找到 .mp4 文件。")
        return

    # Summary
    print(f"找到 {len(files)} 个视频文件:")
    total_dur = 0.0
    for fp in files:
        dur = get_duration_seconds(fp)
        total_dur += dur
        rel = fp.relative_to(repo)
        print(f"  {rel}  ({format_time(dur)})")
    print(f"总时长约: {format_time(total_dur)}")

    if args.dry_run:
        print("\n[dry-run] 不执行转写。")
        return

    # Ensure cache dir
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(MODEL_CACHE)

    # Load model
    print(f"\n加载模型 {args.model} (device={args.device}, compute={args.compute}) ...")
    t0 = time.time()
    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute,
        download_root=str(MODEL_CACHE),
    )
    print(f"模型就绪 ({time.time() - t0:.1f}s)")

    # Transcribe
    print(f"\n开始转写 {len(files)} 个文件...\n")
    ok = fail = skip = 0

    for i, mp4_path in enumerate(files, 1):
        rel = mp4_path.relative_to(repo)
        out_md = mp4_path.with_suffix(".md")

        if out_md.exists() and not args.force:
            print(f"  [{i}/{len(files)}] SKIP (已有): {rel}")
            skip += 1
            continue

        try:
            dur = get_duration_seconds(mp4_path)
            print(f"  [{i}/{len(files)}] 转写中: {rel}  ({format_time(dur)}) ...", flush=True)
            t1 = time.time()

            transcript, detected_dur = transcribe_one(model, mp4_path, args.language)

            elapsed = time.time() - t1
            speed = dur / elapsed if elapsed > 0 else 0

            # Write .md
            md_content = format_markdown(
                mp4_path.stem, transcript, args.model,
                args.language, dur, elapsed,
            )
            out_md.write_text(md_content, encoding="utf-8")
            print(f"        -> {out_md.name}  (速度: {speed:.1f}x, 耗时: {format_time(elapsed)})")
            ok += 1

        except Exception as e:
            print(f"        -> 失败: {e}")
            fail += 1

    print(f"\n完成: {ok} 成功, {skip} 跳过, {fail} 失败")


if __name__ == "__main__":
    main()
