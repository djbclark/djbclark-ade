# 思源笔记模板开发指南

## 概述

思源笔记的模板功能允许用户快速插入预定义的内容片段。模板文件存储在 `data/templates/` 目录下，使用 `.md` 后缀，基于 Go 模板语法。

**重要**：思源笔记模板使用 `.action{}` 语法而非 `{{}}`，以避免与 Markdown 语法冲突。

## 模板语法

### 基本语法

模板中使用 `.action{}` 来包裹变量和表达式：

```template
.action{ 变量或表达式 }
```

示例：
```template
当前文档标题：`.action{ .title }`
当前时间：`.action{ now | date "2006-01-02" }`
```

### 变量赋值

在模板中可以使用 `$` 定义变量：

```template
.action{ $today := now | date "2006-01-02" }
今天的日子是 `.action{ $today }`
```

### 条件判断

```template
.action{ if eq (now | WeekdayCN) "日" }
今天是周日
.action{ else }
今天是工作日
.action{ end }
```

### 循环

```template
.action{ range $blocks }
- ((`.action{ .id }`))
.action{ end }
```

## 日期格式化

Go 的日期格式化使用特殊的固定时间 `2006-01-02 15:04:05`，这个时间点具有唯一性：

| 格式 | 说明 | 示例值 |
|------|------|--------|
| 2006 | 四位年份 | 2026 |
| 01 | 两位月份 | 01-12 |
| 02 | 两位日期 | 01-31 |
| 15 | 24小时制小时 | 00-23 |
| 04 | 分钟 | 00-59 |
| 05 | 秒 | 00-59 |

### 常用日期格式

```template
.action{ now | date "2006-01-02" }           # 2026-01-25
.action{ now | date "2006年01月02日" }        # 2026年01月25日
.action{ now | date "2006-01-02 15:04" }      # 2026-01-25 12:30
.action{ now | date "2006-01-02 15:04:05" }   # 2026-01-25 12:30:45
.action{ now | date "20060102150405" }        # 20260125123045
```

### 日期计算

```template
.action{ $before := (div (now.Sub (toDate "2006-01-02" "2020-02-19")).Hours 24) }
距离 2020-02-19 已经过去 `.action{ $before }` 天
```

## 内置变量

| 变量 | 说明 | 示例 |
|------|------|------|
| title | 当前文档名 | 我的文档 |
| id | 当前文档 ID | 20250101120000-abc123 |
| name | 当前文档命名 | My Document |
| alias | 当前文档别名 | my-document |

示例：
```template
# `.action{ .title }`

文档 ID：`.action{ .id }`
创建时间：`.action{ now | date "2006-01-02 15:04:05" }`
```

## 内置函数

### 数据库查询函数

#### queryBlocks
查询 blocks 表，返回块列表。

```template
.action{ $blocks := queryBlocks "SELECT * FROM blocks WHERE content LIKE '?' LIMIT ?" "%关键词%" "3" }
.action{ range $blocks }
- ((`.action{ .id }`)) `.action{ .content }`
.action{ end }
```

#### getBlock
根据 ID 获取单个块。

```template
.action{ $block := getBlock "20250331162928-53comqi" }
块内容：`.action{ $block.content }`
```

#### querySpans
查询 spans 表。

```template
.action{ $spans := querySpans "SELECT * FROM spans LIMIT ?" "3" }
.action{ range $spans }
- `.action{ .content }`
.action{ end }
```

#### querySQL
执行任意 SQL 查询。

```template
.action{ $refs := querySQL "SELECT * FROM refs LIMIT 3" }
```

### 块统计函数

#### statBlock
统计块内容，返回包含以下字段的对象：
- RuneCount（字符数）
- WordCount（字数）
- LinkCount（链接数）
- ImageCount（图片数）
- RefCount（引用数）
- BlockCount（块数）

```template
.action{ $stats := statBlock .id }
- 字符数：`.action{ $stats.RuneCount }`
- 字数：`.action{ $stats.WordCount }`
- 链接数：`.action{ $stats.LinkCount }`
- 图片数：`.action{ $stats.ImageCount }`
- 引用数：`.action{ $stats.RefCount }`
```

### 路径函数

#### getHPathByID
获取块的可读路径。

```template
.action{ getHPathByID "块ID" }
```

### 时间函数

#### parseTime
解析时间字符串。

```template
.action{ $date := parseTime "20060102" "20231025" }
.action{ $date | date "2006-01-02" }
```

#### Weekday
返回周几（0-6，0 表示周日）。

```template
.action{ now | Weekday }  # 0-6
```

#### WeekdayCN
返回中文周几（日-六）。

```template
今天是 `.action{ now | WeekdayCN }`  # 日、一、二、三、四、五、六
```

#### WeekdayCN2
返回中文周几（天-六）。

```template
今天是 `.action{ now | WeekdayCN2 }`  # 天、一、二、三、四、五、六
```

#### ISOWeek
当前周数。

```template
当前是第 `.action{ now | ISOWeek }` 周
```

#### ISOMonth
当前月份。

```template
当前是第 `.action{ now | ISOMonth }` 月
```

#### ISOYear
当前年份。

```template
当前是 `.action{ now | ISOYear }` 年
```

#### ISOWeekDate
获取指定周几的日期（0-6，0 表示周日）。

```template
本周三是：`.action{ now | ISOWeekDate 3 | date "2006-01-02" }`
```

### 文本统计函数

#### runeCount
统计字符数。

```template
.action{ runeCount "文本内容" }
```

#### wordCount
统计字数。

```template
.action{ wordCount "文本内容" }
```

### 数学函数

#### pow / powf
指数计算。

```template
.action{ pow 2 3 }   # 8 (2的3次方)
.action{ powf 2.5 2 } # 6.25
```

#### log / logf
对数计算。

```template
.action{ log 100 10 }  # 2 (以10为底100的对数)
```

## Sprig 函数库

思源笔记支持 Sprig 函数库，提供了丰富的字符串、日期、数学、逻辑等函数。

### 常用字符串函数

```template
.action{ "  Hello  " | trim }     # "Hello"
.action{ "hello" | upper }        # "HELLO"
.action{ "HELLO" | lower }        # "hello"
.action{ "hello world" | replace "world" "思源" }  # "hello 思源"
```

### 常用日期函数

```template
.action{ now | date "2006-01-02" }
.action{ "2026-01-25" | toDate "2006-01-02" | date "2006年01月" }  # "2026年01月"
```

### 常用数学函数

```template
.action{ add 1 2 }    # 3
.action{ sub 5 2 }    # 3
.action{ mul 3 4 }    # 12
.action{ div 10 2 }   # 5
```

### 常用逻辑函数

```template
.action{ if eq 1 1 }}
相等
.action{ end }

.action{ if and (gt (now | Weekday) 0) (lt (now | Weekday) 6) }}
工作日
.action{ end }}
```

**完整文档**：http://masterminds.github.io/sprig/

## 完整示例

### 示例 1：日期计算模板

```template
.action{ $before := (div (now.Sub (toDate "2006-01-02" "2020-02-19")).Hours 24) }}
.action{ $after := (div ((toDate "2006-01-02" "2048-02-19").Sub now).Hours 24) }}

# 日期统计

今天是 `.action{ now | date "2006-01-02" }}`。

* 距离 `2020-02-19` 已经过去 `.action{ $before }}` 天
* 距离 `2048-02-19` 还剩 `.action{ $after }}` 天
* 当前是第 `.action{ now | ISOWeek }}` 周
* 今天是 `.action{ now | WeekdayCN }}`
```

### 示例 2：查询关键词模板

```template
# 查询结果

.action{ $today := now | date "20060102150405" }}
.action{ $keyword := "思源" }}
.action{ $blocks := queryBlocks "SELECT * FROM blocks WHERE content LIKE '?' AND updated > '?' LIMIT ?" (printf "%%%s%%" $keyword) $today "3" }}

查询到 `.action{ len $blocks }}` 个包含"`.action{ $keyword }}`"的块：

.action{ range $blocks }}
- ((`.action{ .id }}`)) `.action{ .content | trim }}`
.action{ end }}
```

### 示例 3：文档信息统计模板

```template
# 文档信息

## 基本信息

- 标题：`.action{ .title }}`
- ID：`.action{ .id }}`
- 创建时间：`.action{ now | date "2006-01-02 15:04:05" }}`
- 路径：`.action{ getHPathByID .id }}`

## 统计信息

.action{ $stats := statBlock .id }}

| 项目 | 数量 |
|------|------|
| 字符数 | `.action{ $stats.RuneCount }}` |
| 字数 | `.action{ $stats.WordCount }}` |
| 链接数 | `.action{ $stats.LinkCount }}` |
| 图片数 | `.action{ $stats.ImageCount }}` |
| 引用数 | `.action{ $stats.RefCount }}` |
| 块数 | `.action{ $stats.BlockCount }}` |
```

### 示例 4：周报模板

```template
.action{ $today := now }}
.action{ $monday := $today | ISOWeekDate 1 }}
.action{ $sunday := $today | ISOWeekDate 0 }}

# 周报 (`.action{ $monday | date "2006-01-02" }}` ~ `.action{ $sunday | date "2006-01-02" }}`)

## 工作内容

### 本周完成
- 

### 下周计划
- 

## 问题与风险
- 

## 总结

本周第 `.action{ $today | ISOWeek }}` 周，统计共完成 `.action{ wordCount "" }}` 字。
```

## 调用模板

在思源笔记编辑器中：

1. 在文档中输入 `/`
2. 选择"插入模板"
3. 从模板列表中选择需要的模板

或使用快速调用：`/模板名`

## 注意事项

1. **语法差异**：始终使用 `.action{}` 而非 `{{}}`，避免与 Markdown 语法冲突
2. **日期格式**：牢记 `2006-01-02 15:04:05` 这个特殊时间格式
3. **SQL 注入**：使用 `?` 占位符来防止 SQL 注入，而非字符串拼接
4. **性能**：复杂的查询和计算可能影响性能，建议限制结果数量
5. **调试**：可以先将变量输出到文档中查看结果

## 常见问题

### Q: 为什么我的模板不工作？
A: 检查以下几点：
- 确认使用 `.action{}` 语法而非 `{{}}`
- 检查日期格式是否正确
- 查看控制台是否有错误信息
- 确认模板文件是否放在 `data/templates/` 目录

### Q: 如何查询包含特定内容的块？
A: 使用 `queryBlocks` 函数，配合 `LIKE` 语句：
```template
.action{ $blocks := queryBlocks "SELECT * FROM blocks WHERE content LIKE '?' LIMIT ?" "%关键词%" "10" }}
```

### Q: 如何获取当前日期的中文星期？
A: 使用 `WeekdayCN` 或 `WeekdayCN2` 函数：
```template
今天是 `.action{ now | WeekdayCN }}`  # 返回：日、一、二、三、四、五、六
```

### Q: 如何计算两个日期之间的天数？
A: 使用日期相减和除法：
```template
.action{ $days := (div ((toDate "2006-01-02" "2026-12-31").Sub now).Hours 24) }}
距离 2026-12-31 还有 `.action{ $days }}` 天
```
