# 复制到其他 Agent 视口的提示词

把下面整块粘贴到新对话即可。把 `<...>` 换成真实路径。  
仓库根：`f:\agent`。Skill 正文：`skills/course-resource-rename/SKILL.md`。

---

## A. 只处理一章（推荐并行）

```
请严格按项目 Skill 执行课程资源改名。

1. 先 Read 并遵守：
   - f:\agent\skills\course-resource-rename\SKILL.md
   - f:\agent\skills\course-resource-rename\naming.md
2. 你的互斥范围（只允许改这一棵目录，不要动其他章/课）：
   <CHAPTER_PATH>
   例：f:\agent\resources\courses\CAREER201-12年程序员职业跃迁技术与技巧，让你的个人利益最大化[完结]\01 第1章 开局-职场故事，逻辑，素养，现状，路径
3. 先预览，不要直接改：
   & f:\agent\.venv\Scripts\python.exe f:\agent\skills\course-resource-rename\scripts\plan_rename.py --chapter "<CHAPTER_PATH>"
4. 把「旧 → 新」对照表发我确认；若有 NEED_TITLE 先问我。
5. 我回复「直接改」或确认对照表后，再 --apply。
6. 完成后用 --chapter ... --check 汇报是否合规。
7. 不要 git commit。
```

---

## B. 处理整门课（单 Agent，勿与章任务并行）

```
请严格按项目 Skill 执行整课资源改名。

1. 先 Read 并遵守：
   - f:\agent\skills\course-resource-rename\SKILL.md
   - f:\agent\skills\course-resource-rename\naming.md
2. 互斥范围（整课，期间不要另开 Agent 改同一课下的章）：
   <COURSE_PATH>
   例：f:\agent\resources\courses\CAREER201-12年程序员职业跃迁技术与技巧，让你的个人利益最大化[完结]
3. 目标课目录形态：{course_id} {course_title}/（课名保留，去掉 [完结] 等尾巴）
4. 先预览：
   & f:\agent\.venv\Scripts\python.exe f:\agent\skills\course-resource-rename\scripts\plan_rename.py --course "<COURSE_PATH>"
5. 发对照表给我确认后再 --apply；完成后 --check，并确保有 index.json / 各章 module.json。
6. 不要 git commit。
```

---

## C. 只校验（只读）

```
请 Read f:\agent\skills\course-resource-rename\SKILL.md，
对 <COURSE_PATH> 运行 plan_rename.py --check，列出所有不合规项，不要改文件。
```

---

## 并行拆分建议（CAREER201）

每个视口粘贴模板 A，`<CHAPTER_PATH>` 分别填：

1. `...\01 第1章 开局-职场故事，逻辑，素养，现状，路径`
2. `...\02 第2章 攻城-跳槽困惑，时机，方向，方法，悉知`
3. `...\03 第3章 攻城-简历作用，格式，内容，投递`
4. …其余章各开一个视口

**全部章改完后**，再开一个视口用模板 B（或只改课目录名 + `--write-meta`），避免课目录与章任务打架。
