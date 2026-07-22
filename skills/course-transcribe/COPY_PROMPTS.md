# 复制到其他 Agent 视口的提示词

仓库根：`f:\agent`。先 Read `skills/course-transcribe/SKILL.md`。  
有 mp4 的课：**转写主路径**；docx 仅遗留。

---

## A. 转写一门课（推荐）

```
请严格按项目 Skill 转写课程视频。

1. Read：
   - f:\agent\skills\course-transcribe\SKILL.md
   - f:\agent\skills\course-resource-rename\naming.md（确认文件名已规范；未规范先改名）
2. 范围：--course <COURSE_ID>   例：CAREER201
3. 先预览：
   & f:\agent\.venv\Scripts\python.exe f:\agent\skills\course-transcribe\scripts\transcribe_video.py --course <COURSE_ID> --dry-run
4. 中文建议加 --language zh；默认模型 medium。
5. 预览无误后执行转写（不要 --force，除非我明确要求重转）。
6. 抽查 1～2 个 .md 的时间戳与术语，汇报成功/跳过/失败数。
7. 不删 mp4/docx，不 git commit。
```

---

## B. 高精度重转某一课

```
按 skills/course-transcribe/SKILL.md，对 --course <COURSE_ID> 使用
--model large-v3 --language zh --force 重新转写。
先 --dry-run，再执行。不删源文件，不 commit。
```

---

## C. 遗留 docx（无时间戳，慎用）

```
按 skills/course-transcribe/SKILL.md 的【遗留】说明，
对 --course <COURSE_ID> 跑 convert_docx.py --dry-run。
明确告知用户：产出无时间戳，不能替代视频转写进新索引。
未经确认不要 -- 真正写入或删 docx。
```
