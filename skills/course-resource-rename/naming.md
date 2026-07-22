# 课程资源命名规范

与录入方案一致；索引器只接受本规范。

## 目录树

```
resources/courses/
  {course_id} {course_title}/
    index.json
    {CC} {chapter_title}/
      module.json
      {CC}-{LL} {lesson_title}.md
      {CC}-{LL} {lesson_title}.mp4
```

## 正则

| 对象 | 正则 |
|------|------|
| 课目录 | `^(?P<course_id>[a-z0-9][a-z0-9-]*) (?P<course_title>.+)$` |
| 章目录 | `^(?P<cc>\d{2}) (?P<chapter_title>.+)$` |
| 节 stem | `^(?P<section>\d{2}-\d{2}) (?P<title>.+)$` |

- `CC` / `LL`：两位补零；节文件中的 `CC` 必须与所在章目录一致。
- `.md` 与 `.mp4` **同 stem**。

## 字段含义

| 段 | 规则 |
|----|------|
| `course_id` | 机器主键；小写字母/数字/连字符；无空格 |
| `course_title` | **必填**可读课名；与 `index.json.title`、课目录一致；去掉 `[完结]`/渠道水印 |
| `full_title` | 可选，仅 JSON，不进路径 |
| 标题字符 | 允许中文、字母数字、空格、`-_（）()、，.`；禁止 `<>:"/\|?*` 与营销尾巴 |

## 禁止出现在路径中的片段

- `_ev`、`_一手`、`微信`、`[完结]`、`必看` + 感叹号堆砌
- 双重序号：`01 1-1 …`（只保留 `01-01`）
- 课目录只有 id 没有课名，或只有长中文没有 id

## 元数据

`index.json`：

```json
{
  "course_id": "CAREER201",
  "title": "12年程序员职业跃迁技术与技巧",
  "full_title": "可选更长原标题",
  "industry": "IT"
}
```

`module.json`：

```json
{
  "module_id": "CAREER201-ch01",
  "title": "章完整标题",
  "chapter": "01",
  "difficulty": "beginner",
  "tags": []
}
```

## 与转写的顺序

**先改名，再转写**（`course-resource-rename` → `course-transcribe`）。  
`.md` 正文首行必须是 `# {与文件名相同的 stem}`；改名脚本 apply 时会自动同步。

## 迁移对照

| 旧 | 新 |
|----|-----|
| `CAREER201-12年…[完结]/` | `CAREER201 12年程序员职业跃迁技术与技巧/` |
| `01 1-1 标题_一手…[2].md` | `01-01 标题.md` |
| `2-3 解锁…_ev.md` | `02-03 解锁RAG三大核心.md` |
| `第2章 掌握未来…/` | `02 RAG趋势与核心/` |
