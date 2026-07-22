---
name: course-transcribe
description: >-
  将课程视频（.mp4）转为带时间戳的结构化 Markdown 逐字稿，
  或用 auto-fix 规则将旧版 .docx 字幕转为 Markdown。
  使用本地 GPU（faster-whisper）零成本转写。
  当用户要求转写视频、生成逐字稿、处理课程字幕文档时使用。
---

# 课程视频转写与文档化

**项目内权威路径**：`skills/course-transcribe/`（可随仓库复制到任意 Agent 视口使用）。

将 `resources/courses/` 下的 `.mp4` 视频转写为带时间戳的 Markdown 逐字稿。  
也支持将旧版 `.docx` 字幕/文档转换为 Markdown。  
使用本地 GPU（RTX 5070）运行 faster-whisper，不用大模型 API，零成本。

| 文件 | 用途 |
|------|------|
| [auto-fix.md](auto-fix.md) | 自动修正规则表（可自行扩充） |
| [scripts/transcribe_video.py](scripts/transcribe_video.py) | 视频 → 带时间戳 `.md` |
| [scripts/convert_docx.py](scripts/convert_docx.py) | `.docx` 字幕 → Markdown |

## 何时用

- 新增课程视频后，批量生成带时间戳的逐字稿
- 将旧版 `.docx` 课程文档转 Markdown 用于 RAG 知识库
- 用户说：转写视频、生成逐字稿、视频转文字、处理字幕、docx 转 md

## 工作流

```
- [ ] 1. 确认范围（全部课程 / 单个课程 --course xxx）
- [ ] 2. --dry-run 预览视频列表和总时长
- [ ] 3. 执行转写（默认 medium 模型；追求精度用 large-v3）
- [ ] 4. 人工浏览审核生成的 .md
- [ ] 5. 确认无误后删除旧 .docx（如存在）
```

### 视频转写

在仓库根目录 `f:\agent`：

```powershell
# 激活环境
& f:\agent\.venv\Scripts\Activate.ps1

# 预览（列出所有视频，不转写）
python skills/course-transcribe/scripts/transcribe_video.py --dry-run

# 转写全部
python skills/course-transcribe/scripts/transcribe_video.py

# 只转写某个课程
python skills/course-transcribe/scripts/transcribe_video.py --course RAG101

# 中文课程建议指定语言
python skills/course-transcribe/scripts/transcribe_video.py --language zh

# 追求精度用 large-v3（首次下载 ~3GB）
python skills/course-transcribe/scripts/transcribe_video.py --model large-v3

# 强制重新转写
python skills/course-transcribe/scripts/transcribe_video.py --force
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--dry-run` | 否 | 只列出文件，不转写 |
| `--course` | 全部 | 按课程目录名过滤 |
| `--model` | `medium` | `medium`（~1.5GB）或 `large-v3`（~3GB） |
| `--language` | auto | 建议中文用 `zh` |
| `--force` | 否 | 即使已有 `.md` 也重新转写 |
| `--device` | `cuda` | 计算设备 |
| `--compute` | `float16` | 精度类型 |

### docx 转 Markdown

```powershell
python skills/course-transcribe/scripts/convert_docx.py --dry-run
python skills/course-transcribe/scripts/convert_docx.py
python skills/course-transcribe/scripts/convert_docx.py --course RAG101
```

### 清理旧 docx

确认 `.md` 转写质量后：

```powershell
Get-ChildItem -Path "resources/courses" -Recurse -Filter "*.docx" | Remove-Item
```

## 输出格式

每个 `.mp4` 生成一个同名 `.md`（同 stem，符合 naming.md 规范）：

```markdown
# 02-03 解锁RAG三大核心

[0:00] 那到底什么是RAG呢?通过这一小节我们来了解一下。
[0:04] RAG由三个关键的部分组成,第一个是知识库,
[0:10] 第二个是检索,第三个是大语言模型。
```

时间戳格式 `[分:秒]`，方便定位原视频。每次转写自动应用 [auto-fix.md](auto-fix.md) 中的高置信度修正规则。

## 技术细节

| 项目 | 配置 |
|---|---|
| 引擎 | faster-whisper（CTranslate2 优化的 Whisper） |
| 模型缓存 | `F:\agent\.cache\whisper\` |
| 默认模型 | `medium`（~1.5GB，中文 WER ~5-8%） |
| 高精度模型 | `large-v3`（~3GB） |
| 运行设备 | RTX 5070 Laptop GPU, CUDA 12.8, float16 |
| 转写速度 | 约 8-14x 视频时长（medium 模型） |
| VAD 过滤 | 开启，跳过 500ms+ 静音 |
| Beam size | 5 |

## 前置依赖

```powershell
pip install faster-whisper --target f:\jupyter
pip install python-docx --target f:\jupyter   # 仅 docx 转换需要
```

CUDA Toolkit 需已安装（当前 CUDA 12.8）。

## 禁止

- 不删原视频（`.mp4`）
- 未经用户确认不删 `.docx`
- 不擅自 git commit
