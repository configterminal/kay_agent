# 复制到其他 Agent 视口 — 知识切分提示词

把下面整块粘贴到新对话即可。把 `<...>` 换成真实值。
仓库根：`f:\agent`。Skill 正文：`skills/knowledge-split/SKILL.md`。

---

## A. 切分整门课（单 Agent，推荐）

```
请对以下课程执行知识切分。

1. 先 Read 并遵守：
   - f:\agent\skills\knowledge-split\SKILL.md
   - f:\agent\skills\knowledge-split\prompts\split_prompt.py

2. 切分范围（整门课）：
   课程子串：<COURSE_SUBSTR>  例：RAG101

3. 先预览：
   & f:\agent\.venv\Scripts\python.exe skills/knowledge-split/scripts/scan_cues.py --course <COURSE_SUBSTR>

4. 逐节处理：

   对每一节 .md（跳过已有 .knowledge.json 的节）：

   a) 读取 .md 文件，用 SKILL.md 中定义的规则解析 cue 列表
      - 跳过以 # 开头的标题行和空行
      - 匹配 [M:SS] 或 [H:MM:SS] 格式
      - 每条 cue 有 {idx, start_sec, text}

   b) 组装 User Message（用 split_prompt.py 中的 USER_MESSAGE_TEMPLATE）：
      - {course_title}: 从课程目录名或 index.json 获取
      - {chapter}: 章目录名
      - {section} {section_title}: 从 .md 文件名 stem 获取
      - {cues_text}: 格式化为 "[idx] [M:SS] text"，每行一条
      - {max_idx}: len(cues) - 1

   c) 调用 LLM（deepseek-chat，同项目默认 Provider）：
      - system: split_prompt.py 中的 SYSTEM_PROMPT
      - user: 上一步组装的模板
      - temperature: 0.3（降低随机性，保证边界一致）

   d) 解析 LLM 返回的 JSON 数组：
      - 校验 kp_index 连续从 0 开始
      - 校验 cue_start_idx / cue_end_idx 在 [0, max_idx] 范围内
      - 校验相邻知识点之间 cue_end_idx + 1 == cue_start_idx
      - 校验最后一个 cue_end_idx == max_idx
      - 校验失败 → 重试一次；仍失败 → 跳过此节（不写 JSON）

   e) 通过校验后，补全 start_sec / end_sec：
      - start_sec = cues[cue_start_idx].start_sec
      - end_sec = cues[cue_end_idx].start_sec

   f) 写入 .knowledge.json（格式见 SKILL.md）

5. 切分完成后运行预览确认全部标记 ✓：
   & f:\agent\.venv\Scripts\python.exe skills/knowledge-split/scripts/scan_cues.py --course <COURSE_SUBSTR>

6. 抽查 2-3 个 JSON 文件确认边界合理。

7. 不要 git commit。不要修改原 .md 文件。
```

---

## B. 只处理一章（控制范围）

```
请对以下章节执行知识切分。

1. Read skills/knowledge-split/SKILL.md 和 prompts/split_prompt.py
2. 章目录：<CHAPTER_PATH>
   例：f:\agent\resources\courses\RAG101 RAG全栈技术从基础到精通\10 基于知识图谱【金融智库】：从RAG到Graph RAG
3. 其他步骤同上 A 模板，但只扫描该章下的 .md。
4. 不要 git commit。
```

---

## 并行拆分建议

不同 Agent 视口各负责一门课：

| 视口 | 课程子串 |
|------|---------|
| 视口 1 | RAG101 |
| 视口 2 | CAREER201 |

每门课内部也可以按章并行（用模板 B），但确保章之间不重叠。
