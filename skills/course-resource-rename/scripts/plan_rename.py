"""
预览 / 校验 / 应用课程资源改名（符合 naming.md）。

用法（仓库根目录）:
  python .../plan_rename.py --course "resources/courses/<课目录>"
  python .../plan_rename.py --chapter "resources/courses/<课>/<章>"
  python .../plan_rename.py --course "..." --apply
  python .../plan_rename.py --course "..." --check
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

COURSE_DIR_RE = re.compile(r"^(?P<course_id>[A-Za-z0-9][A-Za-z0-9-]*) (?P<course_title>.+)$")
CHAPTER_DIR_RE = re.compile(r"^(?P<cc>\d{2}) (?P<chapter_title>.+)$")
LESSON_STEM_RE = re.compile(r"^(?P<section>\d{2}-\d{2}) (?P<title>.+)$")

# 从脏课目录名抽 course_id：字母+数字货号（如 CAREER201），勿吞掉后面的「-12年…」
DIRTY_COURSE_ID_RE = re.compile(r"^(?P<course_id>[a-zA-Z]+\d+)")
# 节号：1-1 / 01-01 / 2-3
SECTION_IN_NAME_RE = re.compile(r"(?P<a>\d{1,2})-(?P<b>\d{1,2})")
# 章目录开头序号
CHAPTER_PREFIX_RE = re.compile(r"^(?:第\s*)?(?P<n>\d{1,2})\s*")

FORBIDDEN_TITLE_RE = re.compile(
    r"(_ev\b|_一手|微信|\[完结\]|必看[!！]+|一手IT)",
    re.IGNORECASE,
)
WIN_BAD_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


@dataclass
class RenameOp:
    src: Path
    dst: Path
    note: str = ""

    def is_noop(self) -> bool:
        return self.src.resolve() == self.dst.resolve()


def _pad2(n: int | str) -> str:
    return f"{int(n):02d}"


def clean_title(text: str) -> str:
    """去掉营销尾巴与非法字符，压缩空白。"""
    t = text.strip()
    t = re.sub(r"_一手IT课程资源.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"_?微信\d+.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\[完结\]", "", t)
    t = re.sub(r"_ev$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"必看[!！]+", "", t)
    t = re.sub(r"\[\d+\]$", "", t)
    # Windows 半角非法字符；保留中文标点（：？等）
    t = WIN_BAD_CHARS_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" -_")
    # 去掉「必看」等截断后残留的尾逗号/顿号
    t = t.rstrip("，、,;； ")
    return t.strip()


def propose_course_dir(name: str) -> tuple[str, str, str]:
    """
    返回 (course_id, course_title, flag)。
    flag 空=OK；NEED_TITLE=课名需人工确认。
    """
    m = COURSE_DIR_RE.match(name)
    if m:
        return m.group("course_id"), m.group("course_title"), ""

    id_m = DIRTY_COURSE_ID_RE.match(name)
    if not id_m:
        return "unknown", name, "NEED_TITLE"

    course_id = id_m.group("course_id").lower()
    rest = name[len(id_m.group(0)) :].lstrip("-_ ")
    title = clean_title(rest)
    # 常见：过长副标题截到第一个「，」前；务必 strip，避免课目录尾空格
    if "，" in title:
        short, _, _long_tail = title.partition("，")
        if len(short.strip()) >= 6:
            title = short
    title = title.strip()
    flag = "" if title and not FORBIDDEN_TITLE_RE.search(title) else "NEED_TITLE"
    if len(title) < 4:
        flag = "NEED_TITLE"
    return course_id, title, flag


def _strip_chapter_noise(title: str) -> str:
    """去掉「第N章」及首部冗余，得到规范章标题。"""
    t = title.strip()
    t = re.sub(r"^第\s*\d{1,2}\s*章\s*", "", t)
    t = re.sub(r"^章\s*", "", t)
    return clean_title(t)


def propose_chapter_dir(name: str) -> tuple[str, str, str]:
    """返回 (cc, chapter_title, flag)。"""
    m = CHAPTER_DIR_RE.match(name)
    if m:
        cc = m.group("cc")
        raw = m.group("chapter_title")
        title = _strip_chapter_noise(raw)
        if title and title == raw:
            return cc, title, ""
        flag = "NEED_TITLE" if not title else ""
        return cc, title, flag

    n_m = CHAPTER_PREFIX_RE.match(name)
    if not n_m:
        return "00", _strip_chapter_noise(name), "NEED_TITLE"

    cc = _pad2(n_m.group("n"))
    title = _strip_chapter_noise(name[n_m.end() :])
    flag = "NEED_TITLE" if not title else ""
    return cc, title, flag


def propose_lesson_stem(filename_stem: str, chapter_cc: str) -> tuple[str, str, str]:
    """
    返回 (section, title, flag)，section 形如 01-01。
    """
    m = LESSON_STEM_RE.match(filename_stem)
    if m:
        sec = m.group("section")
        if not sec.startswith(chapter_cc + "-"):
            return sec, m.group("title"), "CC_MISMATCH"
        return sec, m.group("title"), ""

    sec_m = SECTION_IN_NAME_RE.search(filename_stem)
    if not sec_m:
        return f"{chapter_cc}-00", clean_title(filename_stem), "NEED_TITLE"

    a, b = _pad2(sec_m.group("a")), _pad2(sec_m.group("b"))
    # 若章号与文件内章号不一致，以章目录为准重写 CC，保留 LL
    if a != chapter_cc:
        section = f"{chapter_cc}-{b}"
        note = "CC_NORMALIZED"
    else:
        section = f"{a}-{b}"
        note = ""

    # 标题：节号之后的部分
    after = filename_stem[sec_m.end() :]
    after = re.sub(r"^[\s_\-]+", "", after)
    # 去掉开头重复的「1-1」类
    title = clean_title(after)
    if not title:
        note = "NEED_TITLE"
    return section, title, note


def lesson_compliant(stem: str, chapter_cc: str) -> bool:
    m = LESSON_STEM_RE.match(stem)
    if not m:
        return False
    if FORBIDDEN_TITLE_RE.search(m.group("title")) or WIN_BAD_CHARS_RE.search(m.group("title")):
        return False
    return m.group("section").startswith(chapter_cc + "-")


def plan_chapter(chapter_dir: Path, course_root_dst: Path | None = None) -> list[RenameOp]:
    """规划一章内的节文件 + 章目录改名。course_root_dst 为课后新根（若课也在改）。"""
    ops: list[RenameOp] = []
    cc, ch_title, flag = propose_chapter_dir(chapter_dir.name)
    new_chapter_name = f"{cc} {ch_title}"
    parent = course_root_dst if course_root_dst is not None else chapter_dir.parent
    new_chapter_dir = parent / new_chapter_name

    for f in sorted(chapter_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".md", ".mp4"}:
            continue
        section, title, lflag = propose_lesson_stem(f.stem, cc)
        new_stem = f"{section} {title}"
        note = ",".join(x for x in (flag, lflag) if x)
        dst = new_chapter_dir / f"{new_stem}{f.suffix.lower()}"
        ops.append(RenameOp(f, dst, note))

    # 章目录本身（含 module.json 等非媒体文件随目录 rename）
    if chapter_dir.resolve() != new_chapter_dir.resolve():
        ops.append(RenameOp(chapter_dir, new_chapter_dir, flag or "DIR"))

    return ops


def plan_course(course_dir: Path) -> list[RenameOp]:
    ops: list[RenameOp] = []
    course_id, course_title, cflag = propose_course_dir(course_dir.name)
    new_course_name = f"{course_id} {course_title}"
    new_course_dir = course_dir.parent / new_course_name

    chapters = sorted(
        [p for p in course_dir.iterdir() if p.is_dir() and p.name != "__pycache__"],
        key=lambda p: p.name,
    )
    for ch in chapters:
        ops.extend(plan_chapter(ch, course_root_dst=new_course_dir))

    if course_dir.resolve() != new_course_dir.resolve():
        ops.append(RenameOp(course_dir, new_course_dir, cflag or "DIR"))

    return ops


def dedupe_dir_ops(ops: list[RenameOp]) -> list[RenameOp]:
    """节文件先于目录；同一 src 只保留一条。"""
    files = [o for o in ops if o.src.is_file() or (not o.src.exists() and o.src.suffix)]
    dirs = [o for o in ops if o.src.is_dir() or o.note == "DIR" or "DIR" in o.note]
    # 上面 is_file 在规划时路径仍存在
    files = [o for o in ops if o.src.exists() and o.src.is_file()]
    dirs = [o for o in ops if o.src.exists() and o.src.is_dir()]
    seen: set[Path] = set()
    out: list[RenameOp] = []
    for o in files + dirs:
        key = o.src.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def print_ops(ops: list[RenameOp]) -> int:
    need = 0
    for o in ops:
        if o.is_noop():
            continue
        mark = f"  [{o.note}]" if o.note else ""
        print(f"{o.src} → {o.dst}{mark}")
        if "NEED_TITLE" in o.note or "CC_MISMATCH" in o.note:
            need += 1
    return need


def sync_md_h1(md_path: Path) -> None:
    """将 .md 首行 # 标题同步为文件 stem（与命名规范一致）。"""
    if md_path.suffix.lower() != ".md" or not md_path.is_file():
        return
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_h1 = f"# {md_path.stem}"
    if lines and lines[0].startswith("# "):
        if lines[0] == new_h1:
            return
        lines[0] = new_h1
        md_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    else:
        body = text.lstrip("\n")
        md_path.write_text(f"{new_h1}\n\n{body}", encoding="utf-8")
    print(f"H1  {md_path}")


def apply_ops(ops: list[RenameOp]) -> None:
    """先文件后目录；目录用 move 整棵子树（此时子文件应已在新相对结构——见下）。"""
    # 实际策略：对每个「章」：先在临时/直接创建新章目录，移动文件，再删旧章；
    # 简化：仅 shutil.move 每个非 noop 的文件；最后 move 仍存在的旧章/旧课目录。
    files = [o for o in ops if o.src.exists() and o.src.is_file() and not o.is_noop()]
    dirs = [o for o in ops if o.src.exists() and o.src.is_dir() and not o.is_noop()]
    # 目录按路径深度降序（先深后浅）
    dirs.sort(key=lambda o: len(o.src.parts), reverse=True)

    for o in files:
        if "NEED_TITLE" in o.note:
            raise SystemExit(f"拒绝 apply：存在 NEED_TITLE → {o.src}")
        o.dst.parent.mkdir(parents=True, exist_ok=True)
        if o.dst.exists():
            raise SystemExit(f"目标已存在: {o.dst}")
        print(f"MOVE {o.src} → {o.dst}")
        shutil.move(str(o.src), str(o.dst))
        # 改名后同步 md 内标题，避免「文件名对了、# 标题仍是脏名」
        sync_md_h1(o.dst)

    for o in dirs:
        if "NEED_TITLE" in o.note:
            raise SystemExit(f"拒绝 apply：存在 NEED_TITLE → {o.src}")
        # 若目录已空或只剩 json，整目录改名
        if o.dst.exists():
            # 把剩余文件并入
            for child in list(o.src.iterdir()):
                target = o.dst / child.name
                if target.exists():
                    raise SystemExit(f"目标已存在: {target}")
                shutil.move(str(child), str(target))
            o.src.rmdir()
            print(f"MERGE-REMOVE {o.src}")
        else:
            o.dst.parent.mkdir(parents=True, exist_ok=True)
            print(f"MOVE {o.src} → {o.dst}")
            shutil.move(str(o.src), str(o.dst))


def check_course(course_dir: Path) -> int:
    """返回不合规项数量。"""
    errors = 0
    cm = COURSE_DIR_RE.match(course_dir.name)
    if not cm:
        print(f"FAIL course dir: {course_dir.name}")
        errors += 1
        course_id = "???"
    else:
        course_id = cm.group("course_id")
        print(f"OK course: {course_dir.name}")

    index = course_dir / "index.json"
    if not index.exists():
        print(f"FAIL missing index.json")
        errors += 1
    else:
        data = json.loads(index.read_text(encoding="utf-8"))
        if cm and (
            data.get("course_id") != cm.group("course_id")
            or data.get("title") != cm.group("course_title")
        ):
            print(
                f"FAIL index.json mismatch: "
                f"course_id={data.get('course_id')!r} title={data.get('title')!r}"
            )
            errors += 1

    for ch in sorted([p for p in course_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
        hm = CHAPTER_DIR_RE.match(ch.name)
        if not hm:
            print(f"FAIL chapter dir: {ch.name}")
            errors += 1
            continue
        cc = hm.group("cc")
        print(f"OK chapter: {ch.name}")
        if not (ch / "module.json").exists():
            print(f"  WARN missing module.json: {ch}")
        for f in sorted(ch.iterdir()):
            if f.suffix.lower() not in {".md", ".mp4"}:
                continue
            if not lesson_compliant(f.stem, cc):
                print(f"FAIL lesson: {f.name}")
                errors += 1
            else:
                print(f"  OK {f.name}")
            # md 首行 # 须与 stem 一致
            if f.suffix.lower() == ".md":
                try:
                    first = f.read_text(encoding="utf-8").splitlines()[:1]
                    expect = f"# {f.stem}"
                    if not first or first[0] != expect:
                        print(f"FAIL md H1 != stem: {f.name}")
                        if first:
                            print(f"       got: {first[0][:80]}")
                        errors += 1
                except OSError as e:
                    print(f"FAIL read {f.name}: {e}")
                    errors += 1
    return errors


def ensure_metadata_after_rename(course_dir: Path) -> None:
    """课目录已合规时，补齐 index.json；章补 module.json。"""
    m = COURSE_DIR_RE.match(course_dir.name)
    if not m:
        return
    course_id = m.group("course_id")
    title = m.group("course_title")
    index = course_dir / "index.json"
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
    else:
        data = {}
    data["course_id"] = course_id
    data["title"] = title
    data.setdefault("industry", "IT")
    index.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WRITE {index}")

    for ch in course_dir.iterdir():
        if not ch.is_dir():
            continue
        hm = CHAPTER_DIR_RE.match(ch.name)
        if not hm:
            continue
        cc = hm.group("cc")
        mod = ch / "module.json"
        if mod.exists():
            md = json.loads(mod.read_text(encoding="utf-8"))
        else:
            md = {}
        md["module_id"] = f"{course_id}-ch{cc}"
        md["chapter"] = cc
        md.setdefault("title", hm.group("chapter_title"))
        md.setdefault("difficulty", "beginner")
        md.setdefault("tags", [])
        mod.write_text(json.dumps(md, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"WRITE {mod}")


def main() -> int:
    # Windows 控制台避免中文路径乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="课程资源改名预览/校验/应用")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--course", type=str, help="课目录相对/绝对路径")
    g.add_argument("--chapter", type=str, help="章目录相对/绝对路径")
    parser.add_argument("--apply", action="store_true", help="执行改名")
    parser.add_argument("--check", action="store_true", help="只校验合规性")
    parser.add_argument(
        "--write-meta",
        action="store_true",
        help="在课目录已合规时补写 index.json / module.json",
    )
    args = parser.parse_args()

    if args.course:
        course_dir = Path(args.course).resolve()
        if not course_dir.is_dir():
            print(f"不是目录: {course_dir}", file=sys.stderr)
            return 2
        if args.check:
            n = check_course(course_dir)
            return 1 if n else 0
        if args.write_meta:
            ensure_metadata_after_rename(course_dir)
            return 0
        ops = dedupe_dir_ops(plan_course(course_dir))
        need = print_ops(ops)
        if args.apply:
            if need:
                print(f"有 {need} 处 NEED_TITLE/CC_MISMATCH，请先改标题再 --apply", file=sys.stderr)
                return 1
            apply_ops(ops)
            # apply 后课目录可能已变
            new_id, new_title, _ = propose_course_dir(course_dir.name)
            # 若已 move，用目标路径
            final = None
            for o in ops:
                if o.src == course_dir or o.src.resolve() == course_dir.resolve():
                    final = o.dst
            if final is None:
                # 课目录名可能本就合规
                final = course_dir.parent / f"{new_id} {new_title}"
                if not final.exists():
                    final = course_dir
            if final.exists():
                ensure_metadata_after_rename(final)
        return 0

    # chapter 模式
    chapter_dir = Path(args.chapter).resolve()
    if not chapter_dir.is_dir():
        print(f"不是目录: {chapter_dir}", file=sys.stderr)
        return 2
    if args.check:
        # 包装成临时检查：只查该章
        hm = CHAPTER_DIR_RE.match(chapter_dir.name)
        if not hm:
            print(f"FAIL chapter dir: {chapter_dir.name}")
            return 1
        cc = hm.group("cc")
        err = 0
        for f in chapter_dir.iterdir():
            if f.suffix.lower() in {".md", ".mp4"} and not lesson_compliant(f.stem, cc):
                print(f"FAIL lesson: {f.name}")
                err += 1
        return 1 if err else 0

    ops = dedupe_dir_ops(plan_chapter(chapter_dir))
    need = print_ops(ops)
    if args.apply:
        if need:
            print(f"有 {need} 处需人工确认，中止", file=sys.stderr)
            return 1
        apply_ops(ops)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
