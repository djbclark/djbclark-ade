# 内容块操作指南

## 内容块定义

内容块是思源笔记的基本单位，每个块通过全局唯一 ID 标识。

- **ID 格式**：由时间戳和 7 位随机字符组成，形如 `202008250000-a1b2c3d`
- **唯一性**：整个笔记库中每个块的 ID 都是唯一的
- **层次结构**：块可以嵌套，形成文档树状结构

---

## 内容块类型详解

### 块类型代码对照表

| 代码 | 类型 | 元类型 | 说明 |
|------|------|--------|------|
| `d` | 文档块 | 容器块 | 根节点，代表整个文档 |
| `h` | 标题块 | 叶子块 | 文档标题，支持 h1-h6 |
| `p` | 段落块 | 叶子块 | 普通文本段落 |
| `l` | 列表块 | 容器块 | 有序/无序/任务列表容器 |
| `i` | 列表项块 | 容器块 | 列表中的单个项目 |
| `b` | 引述块 | 容器块 | 引用块容器 |
| `callout` | 提示块 | 容器块 | 提示/警告/说明框 |
| `s` | 超级块 | 容器块 | 块组容器 |
| `c` | 代码块 | 叶子块 | 代码片段 |
| `m` | 公式块 | 叶子块 | 数学公式 |
| `t` | 表格块 | 叶子块 | 表格 |
| `av` | 数据库块 | 叶子块 | 属性视图数据库 |
| `query_embed` | 嵌入块 | 叶子块 | SQL 查询嵌入 |
| `html` | HTML 块 | 叶子块 | HTML 内容 |
| `video` | 视频块 | 叶子块 | 视频文件 |
| `audio` | 音频块 | 叶子块 | 音频文件 |
| `widget` | 挂件块 | 叶子块 | 自定义小部件 |
| `iframe` | IFrame 块 | 叶子块 | 嵌入网页 |
| `tb` | 分隔线 | 叶子块 | 水平分隔线 |

### 子类型（subtype）

**列表块 / 列表项块**：
- `o`：有序列表（1. 2. 3.）
- `u`：无序列表（• • •）
- `t`：任务列表（- [ ] - [x]）

**标题块**：
- `h1` ~ `h6`：标题层级

**提示块**：
- `NOTE`：提示
- `TIP`：小贴士
- `IMPORTANT`：重要
- `WARNING`：警告
- `CAUTION`：注意

---

## 块引用语法

### 引用语法格式

```markdown
((块ID "静态锚文本"))   -- 静态锚文本，不会跟随定义块内容变化
((块ID '动态锚文本'))   -- 动态锚文本，会跟随定义块内容变化
((块ID))               -- 使用动态锚文本，锚文本为块内容
```

### 使用示例

```markdown
# 创建引用文档

((20210808180117-czj9bvb "这是引用"))      -- 静态锚文本
((20210808180117-czj9bvb '这是引用'))      -- 动态锚文本
((20210808180117-czj9bvb))                 -- 使用块内容
```

### 触发方式

- **触发搜索**：输入 `((` 会自动触发块引用搜索面板
- **文档搜索**：输入 `[[` 仅搜索文档块（需在设置中开启）
- **快捷键**：
  - 直接回车：使用动态锚文本
  - Ctrl+回车：使用静态锚文本

### 引用特点

- **静态锚文本**：锚文本固定，不受引用块内容变化影响
- **动态锚文本**：锚文本跟随引用块内容自动更新
- **跨文档引用**：可引用任何文档中的任意块
- **反向链接**：引用块会自动生成反向链接

---

## 嵌入块语法

### 语法格式

```markdown
{{ SQL 查询语句 }}
```

### 基础查询示例

**查询包含关键字的块**：
```sql
{{ SELECT * FROM blocks WHERE content LIKE '%关键字%' }}
```

**查询特定类型的块**：
```sql
{{ SELECT * FROM blocks WHERE type = 'i' AND content LIKE '%内容块%' }}
```

**查询最近更新的标题**：
```sql
{{ SELECT * FROM blocks WHERE type = 'h' ORDER BY updated DESC LIMIT 5 }}
```

### 常用查询场景

**查询未完成任务**：
```sql
{{ SELECT * FROM blocks WHERE markdown LIKE '%- [ ]%' }}
```

**随机漫游**：
```sql
{{ SELECT * FROM blocks ORDER BY random() LIMIT 1 }}
```

**查询特定文档的块**：
```sql
{{ SELECT * FROM blocks WHERE root_id = '文档ID' AND type = 'p' }}
```

**查询包含特定属性的块**：
```sql
{{ SELECT * FROM blocks WHERE id IN (
    SELECT block_id FROM attributes
    WHERE name = 'custom-priority' AND value = '1'
) }}
```

### 查询说明

- **默认限制**：默认 LIMIT 为 64 条，可在设置中调整
- **实时更新**：嵌入块会根据查询结果实时更新
- **支持 JOIN**：可与其他表（如 attributes）关联查询
- **排序支持**：支持 ORDER BY 子句

---

## 内容块属性

### 系统属性

| 属性名 | 描述 | 用途 |
|--------|------|------|
| `name` | 内容块的命名 | 块的唯一标识名称 |
| `alias` | 内容块的别名 | 可设置多个别名，逗号分隔 |
| `memo` | 内容块的备注 | 纯文本备注信息 |
| `bookmark` | 内容块的书签 | 书签标记 |

### 自定义属性

**命名规则**：
- 属性名仅允许小写字母和数字
- 必须以字母开头
- 示例：`doing`、`day1`、`priority`

**存储方式**：
- 系统会自动添加 `custom-` 前缀
- 实际存储为 `custom-priority`、`custom-status` 等

**设置属性**：
```markdown
在块的 IAL（内联属性列表）中设置：
{: custom-priority="1" custom-status="doing" custom-day1="2025-01-01"}
```

### 基于属性的查询

**单属性查询**：
```sql
SELECT * FROM blocks WHERE id IN (
    SELECT block_id FROM attributes
    WHERE name = 'custom-priority' AND value = '1'
);
```

**多属性组合查询**：
```sql
SELECT * FROM blocks WHERE id IN (
    SELECT block_id FROM attributes AS a
    WHERE (a.name = 'custom-progress' AND a.value = '30')
       OR (a.name = 'custom-priority' AND a.value = '2')
    GROUP BY block_id HAVING count(block_id) = 2
);
```

**查询特定文档的属性块**：
```sql
SELECT * FROM blocks
WHERE root_id = '文档ID'
  AND id IN (
      SELECT block_id FROM attributes
      WHERE name = 'custom-status' AND value = 'doing'
  );
```

---

## blocks 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 内容块 ID（主键） |
| `parent_id` | TEXT | 父块 ID，文档块为空 |
| `root_id` | TEXT | 根块 ID（即文档块 ID） |
| `box` | TEXT | 笔记本 ID |
| `path` | TEXT | 文档路径 |
| `hpath` | 人类可读的文档路径 |
| `name` | TEXT | 内容块名称 |
| `alias` | TEXT | 内容块别名 |
| `memo` | TEXT | 内容块备注 |
| `content` | TEXT | 去除 Markdown 标记的纯文本 |
| `fcontent` | TEXT | 第一个子块的文本 |
| `markdown` | TEXT | 包含完整 Markdown 的文本 |
| `type` | TEXT | 内容块类型（d/h/p/l/i/b/c/m/t 等） |
| `subtype` | TEXT | 内容块子类型（o/u/t/h1~h6 等） |
| `ial` | TEXT | 内联属性列表 `{: name="value"}` |
| `created` | INTEGER | 创建时间（如 20221013202001） |
| `updated` | INTEGER | 更新时间 |

### 字段说明

**ID 相关**：
- `id`：全局唯一标识，用于块引用和查询
- `parent_id`：指向父块的 ID，文档块为 NULL
- `root_id`：始终指向文档块的 ID

**路径相关**：
- `box`：所属笔记本 ID
- `path`：文档的系统路径（如 `/2025/01/test.md`）
- `hpath`：人类可读路径（如 `/2025/01/测试文档/`）

**内容相关**：
- `content`：去除 Markdown 符号的纯文本内容
- `fcontent`：第一个子块的内容（快速预览）
- `markdown`：完整的 Markdown 文本，包含格式标记

**类型相关**：
- `type`：块类型代码（p/h/l/i 等）
- `subtype`：子类型（o/u/t/h1~h6 等）

**时间格式**：
- `created` 和 `updated`：整型时间戳，格式为 `YYYYMMDDHHmmss`
- 示例：`20221013202001` 表示 2022年10月13日 20:20:01

---

## 使用建议

### 块引用最佳实践

1. **使用动态锚文本**：需要锚文本随引用内容自动更新时
2. **使用静态锚文本**：需要锚文本固定不变时，如文档索引
3. **合理命名**：给重要块设置 `name` 属性，便于引用和管理
4. **批量替换**：使用块引用可以在一处修改，多处同步更新

### 嵌入块应用场景

1. **数据汇总**：汇总多个文档的特定类型块
2. **任务管理**：查询所有未完成任务列表
3. **知识索引**：按主题或标签聚合相关内容
4. **随机回顾**：使用 `ORDER BY random()` 进行知识漫游

### 属性管理建议

1. **规范命名**：统一使用小写字母和数字，避免特殊字符
2. **语义化属性**：使用有意义的属性名，如 `priority`、`status`、`deadline`
3. **批量操作**：通过嵌入块结合属性查询实现自动化管理
4. **避免过度复杂**：保持属性结构简洁，便于查询和维护
