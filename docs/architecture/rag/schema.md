# schema.py — Milvus Schema 定义

> 改字段须 `drop_collection` + `build_index(force=True)`（Milvus Lite 不支持原地加列）。

```
┌─────────────────────────────────────────────────────────────┐
│                    schema.py                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Collection: course_content                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ id          VARCHAR  128  主键  auto_id=False       │   │
│  │ content     VARCHAR  65535 文本（去时间戳纯文本）     │   │
│  │ embedding   FLOAT_VECTOR  1024维（BGE-large-zh）    │   │
│  │ parent_id   VARCHAR  128  父文档ID                  │   │
│  │ course_id   VARCHAR  128  课程标识                  │   │
│  │ chapter     VARCHAR  512  章节目录名                │   │
│  │ section     VARCHAR  64   节号 "02-03"              │   │
│  │ title       VARCHAR  512  标题                      │   │
│  │ file_type   VARCHAR  16   md                        │   │
│  │ chunk_index INT16         子:0/1/2  父:-1           │   │
│  │ tags        VARCHAR  1024 标签（逗号分隔）           │   │
│  │ start_sec   INT32         块起始秒；父=-1           │   │
│  │ end_sec     INT32         块结束秒；父=-1           │   │
│  │ media_path  VARCHAR  1024 相对 resources/ 的 mp4    │   │
│  │ ─────────── 知识切分字段（优先 .knowledge.json）──── │   │
│  │ kp_title    VARCHAR  256  知识点标题；无则 ""       │   │
│  │ kp_summary  VARCHAR  1024 知识点摘要                │   │
│  │ kp_index    INT16         节内序号 0/1/2；无则 -1   │   │
│  │ key_points  VARCHAR  2048 要点列表（逗号分隔）       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Index: embedding → HNSW (M=16, efConstruction=200, COSINE) │
│                                                             │
│  # 子文档：有向量，参与搜索。知识点模式对 search_text        │
│  #   （kp_title+kp_summary+key_points）做 embedding          │
│  # 父文档：全零向量占位，命中后通过 parent_id 取整节上下文    │
│  # 知识切分：同目录 .knowledge.json 存在时自动使用            │
│  #   absence → fallback 规则时间/字数窗口                   │
└─────────────────────────────────────────────────────────────┘
```
