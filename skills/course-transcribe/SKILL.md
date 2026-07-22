---
name: course-transcribe
description: >-
  将课程视频（.mp4）转为带时间戳的结构化 Markdown 逐字稿（faster-whisper 本地 GPU）。
  含遗留 docx→md（无时间戳，不作为新索引源）。
  当用户要求转写视频、生成逐字稿、处理课程字幕时使用。
---

# 课程视频转写与文档化

**项目内权威路径**：`skills/course-transcribe/`。

将 `resources/courses/` 下 `.mp4` 转写为**带时间戳**的同名 `.md`（新录入唯一源形态）。  
使用本地 GPU（faster-whisper），不走大模型 API。

| 文件 | 用途 |
|------|------|
| [auto-fix.md](auto-fix.md) | 修正规则说明 |
| [scripts/auto_fix_rules.py](scripts/auto_fix_rules.py) | 共用 AUTO_FIX / FLAG_ONLY |
| [scripts/transcribe_video.py](scripts/transcribe_video.py) | **主路径**：视频 → 带时间戳 `.md` |
| [scripts/convert_docx.py](scripts/convert_docx.py) | **遗留**：`.docx` → 无时间戳 md |
| [COPY_PROMPTS.md](COPY_PROMPTS.md) | 复制到其他 Agent 视口 |

命名规范见 [`../course-resource-rename/naming.md`](../course-resource-rename/naming.md)。

## 强制顺序（必须遵守）

1. **先改名**（`course-resource-rename`）→ 合规 `{CC}-{LL} 标题.mp4`（及已有 md 同步改名）
2. **再转写** → 生成同 stem `.md`；`#` 标题 = 文件 stem
3. 人工抽查时间戳与术语
4. （可选）确认后删旧 `.docx`——须用户明确同意

**禁止**未改名先转写：否则 `#` 标题与文件名会残留营销后缀/旧序号，还要二次修正文。  
若已有 md 仅改了文件名：须把正文首行 `# …` 改成与 **新 stem** 一致（改名 Skill 的 apply 会同步；存量可批量修）。

## 何时用

- 新增/补齐课程视频的带时间戳逐字稿
- 用户说：转写视频、生成逐字稿、视频转文字
- docx 仅过渡：无 mp4 或只要可读 md 时；**不要**当新 RAG 唯一源

## 工作流

```
- [ ] 1. 确认范围（--course CAREER201 等）
- [ ] 2. --dry-run 预览视频与总时长
- [ ] 3. 转写（默认 medium；要精度加 --model large-v3）
- [ ] 4. 抽查 .md 时间戳与术语
- [ ] 5. 用户确认后再删旧 .docx（如有）
```

### 视频转写（主路径）

仓库根目录 `f:\agent`：

```powershell
& f:\agent\.venv\Scripts\Activate.ps1

python skills/course-transcribe/scripts/transcribe_video.py --dry-run
python skills/course-transcribe/scripts/transcribe_video.py --course CAREER201 --language zh
python skills/course-transcribe/scripts/transcribe_video.py --course CAREER201 --model large-v3 --language zh
python skills/course-transcribe/scripts/transcribe_video.py --force
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--dry-run` | 否 | 只列表 |
| `--course` | 全部 | 路径子串，如 `CAREER201` |
| `--model` | `medium` | 精度可选 `large-v3` |
| `--language` | auto | 中文建议 `zh` |
| `--force` | 否 | 已有同名 `.md` 也重转 |
| `--device` | `cuda` | |
| `--compute` | `float16` | |

### docx → md（遗留）

产出**无** `[M:SS]` 时间戳，不能替代视频转写进新索引。

```powershell
python skills/course-transcribe/scripts/convert_docx.py --dry-run
python skills/course-transcribe/scripts/convert_docx.py --course RAG101
```

### 清理旧 docx

**须用户明确确认**后再删：

```powershell
Get-ChildItem -Path "resources/courses" -Recurse -Filter "*.docx" | Remove-Item
```

## 输出格式（真实样例）

每个 `.mp4` → 同 stem `.md`。**只含标题 + 时间戳正文**（不写模型/语言/耗时，避免进 RAG 噪声）：

```markdown
# 02-03 解锁RAG三大核心

[0:00] 那到底什么是RAG呢？通过这一小节，我们来了解一下。
[0:04] RAG由三个关键的部分组成，第一个是知识库，
[1:05] ……
```

时长 ≥1 小时用 `[H:MM:SS]`。转写时自动应用 `auto_fix_rules.py` 高置信修正。

## 技术细节

| 项目 | 配置 |
|------|------|
| 引擎 | faster-whisper |
| 模型缓存 | `F:\agent\.cache\whisper\`（仅 `download_root`，不改全局 `HF_HOME`） |
| 默认模型 | `medium` |
| 高精度 | `large-v3`（`--model`） |
| VAD | 开，静音 ≥500ms 跳过 |
| Beam | 5 |

## 前置依赖

```powershell
pip install faster-whisper --target f:\jupyter
pip install python-docx --target f:\jupyter   # 仅遗留 docx 需要
```

## 禁止

- 不删原视频 `.mp4`
- 未经用户确认不删 `.docx`
- 不擅自 git commit
- 不把无时间戳的 docx 产物当成新索引唯一源
