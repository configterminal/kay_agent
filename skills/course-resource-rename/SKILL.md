---
name: course-resource-rename
description: >-
  Renames course resource directories and lesson files under resources/courses/
  to the project's timestamped-md naming standard (course_id + course_title,
  CC chapter folders, CC-LL lesson stems, paired .md/.mp4). Use when the user
  asks to rename course files, normalize resources, fix non-compliant lesson
  names, or parallelize renaming of chapters/courses.
---

# 课程资源按规范改名

**项目内权威路径**：`skills/course-resource-rename/`（可随仓库复制到任意 Agent 视口使用）。

将 `resources/courses/` 下不合规的课目录、章目录、节文件改成项目约定命名。  
**改路径/文件名 + 必要的 `index.json` / `module.json`；若目标是 `.md`，同步把首行 `#` 标题改成新 stem。不改时间戳正文。**

与转写的强制顺序：**先本 Skill 改名 → 再 `course-transcribe` 转写**（勿颠倒）。

| 文件 | 用途 |
|------|------|
| [naming.md](naming.md) | 命名规范全文 |
| [COPY_PROMPTS.md](COPY_PROMPTS.md) | **复制到其他 Agent 视口的提示词模板** |
| [scripts/plan_rename.py](scripts/plan_rename.py) | 预览 / apply / check |

## 其他视口怎么用

1. 打开 [COPY_PROMPTS.md](COPY_PROMPTS.md)，复制对应模板到新 Agent 对话。
2. 该 Agent **第一步**必须：`Read skills/course-resource-rename/SKILL.md` 与 `naming.md`。
3. 严格遵守并行互斥：一 Agent 只动一门课或一章。

## 何时用

- 用户说：按规范改名、规范化课程资源、修文件名、批量 rename
- 并行：每个 Agent **只负责一门课，或一门课里的一章**

## 并行规则（必须遵守）

1. **互斥范围**：一次任务只动一个目录树（整课或单章）。禁止两 Agent 同改一课。
2. **先预览后执行**：先对照表，用户确认（或明确说「直接改」）再 `move`。
3. **成对移动**：同一节 `.md` 与 `.mp4` 同新 stem；缺 mp4 可只改 md。
4. **先深后浅**：节文件 → 章目录 → 课目录。
5. **Windows**：用 Python `pathlib` / `shutil.move`。

## 工作流

```
- [ ] 1. 锁定范围（一门课或一章）
- [ ] 2. 跑预览脚本 / 手写对照表
- [ ] 3. 确认 course_id、course_title、章/节标题
- [ ] 4. 执行改名（节 → 章 → 课）
- [ ] 5. 补齐或校正 index.json / module.json
- [ ] 6. 再跑校验：不合规列表为空
```

### 预览 / 应用 / 校验

在仓库根目录 `f:\agent`：

```powershell
& f:\agent\.venv\Scripts\python.exe skills/course-resource-rename/scripts/plan_rename.py --course "resources/courses/<课目录名>"
& f:\agent\.venv\Scripts\python.exe skills/course-resource-rename/scripts/plan_rename.py --chapter "resources/courses/<课>/<章>"
& f:\agent\.venv\Scripts\python.exe skills/course-resource-rename/scripts/plan_rename.py --course "..." --apply
& f:\agent\.venv\Scripts\python.exe skills/course-resource-rename/scripts/plan_rename.py --course "..." --check
& f:\agent\.venv\Scripts\python.exe skills/course-resource-rename/scripts/plan_rename.py --course "..." --write-meta
```

脚本打印：`旧路径 → 新路径`；出现 `NEED_TITLE` 必须先问用户。

### 标题怎么定

| 层级 | 来源优先级 |
|------|------------|
| `course_id` | 目录前缀 / 已有 `index.json` / 用户指定 |
| `course_title` | **必填**可读课名；去掉 `[完结]`、渠道水印；与目录及 `index.json.title` 一致 |
| 章标题 | 现章目录语义压缩（去掉「第N章」）；完整长名可进 `module.json.title` |
| 节标题 | 剥掉营销后缀后的核心名；用户可覆盖 |

### 元数据

- 课根：`index.json` → `course_id`、`title`（= 目录课名）；可选 `full_title`
- 章：`module.json` → `module_id`=`{course_id}-ch{CC}`、`title`、`chapter`、`tags`、`difficulty`

## 目标形态

```
resources/courses/{course_id} {course_title}/
  index.json
  {CC} {chapter_title}/
    module.json
    {CC}-{LL} {lesson_title}.md
    {CC}-{LL} {lesson_title}.mp4
```

## 禁止

- 不删视频/文稿；不重写转写时间戳（除非用户另任务）
- 路径中禁止：`[完结]`、`_ev`、`一手IT`、微信号、双重序号 `01 1-1`
- 不做脏名模糊兼容；不擅自 git commit
