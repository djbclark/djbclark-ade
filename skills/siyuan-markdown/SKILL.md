---
name: siyuan-markdown
description: 思源笔记风味 Markdown（SFMD）编辑器，处理维基链接、块引用、嵌入块、属性查询等思源特有语法。当编辑思源 .md 文件、插入图片、使用双链语法时使用此技能（格式层，依赖 siyuan 基础知识）。
---

# 思源笔记风味 Markdown (SFMarkdown)

## 概述

思源笔记风味 Markdown 是在标准 Markdown 基础上扩展的一套语法，支持块级引用、双向链接、属性查询、SQL 嵌入等思源笔记特有的功能。

## 维基链接

### 文档链接

```markdown
[[文档名称]]              // 链接到同名文档
[[文档名称|显示别名]]    // 链接到文档并显示自定义名称
```

### 块级链接

```markdown
((块ID))                 // 引用特定块
```

每个思源笔记块都有唯一的块 ID，格式类似 `20250125000000-1a2b3c4d`。

### 协议链接

```markdown
siyuan://blocks/块ID     // 使用 siyuan:// 协议直接跳转到块
```

## 嵌入语法

思源笔记提供三种块引用方式：

### 引用块

右键点击内容块 → 复制 → 引用块

```markdown
> ((20250125000000-1a2b3c4d))
```

- 引用块会显示引用标记
- 源内容更新时，所有引用处自动更新
- 可以通过引用跳转到源内容

### 嵌入块

右键点击内容块 → 复制 → 嵌入块

嵌入块直接显示原始内容，保留格式和样式。

### 块超链接

允许跳转到笔记内的任意块，是比文档小一级的基本单位。

## 标注和高亮

### 引用块

```markdown
> 这是一段引用文本
```

### 行内代码

```markdown
这是一段 `行内代码` 示例
```

### 粗体和斜体

```markdown
**粗体文本**
*斜体文本*
***粗斜体文本***
```

### 删除线

```markdown
~~删除线文本~~
```

### 下划线

```markdown
<u>下划线文本</u>
```

## 属性和元数据

思源笔记支持自定义属性功能。

### 添加属性

可以为任意块添加自定义属性，通过思源笔记界面设置或通过 API 添加。

### SQL 查询嵌入

```markdown
```sql
SELECT * FROM blocks WHERE type='d'
```
```

使用 SQL 查询来动态获取和显示块内容。

### 标签系统

```markdown
#标签名
```

支持文档树和块引重构的标签系统。

## 列表语法

### 无序列表

```markdown
- 列表项 1
- 列表项 2
  - 子列表项 2.1
  - 子列表项 2.2
```

### 有序列表

```markdown
1. 列表项 1
2. 列表项 2
   1. 子列表项 2.1
   2. 子列表项 2.2
```

### 任务列表

```markdown
- [ ] 未完成任务
- [x] 已完成任务
```

## 代码块

```markdown
\```python
def hello():
    print("Hello, SiYuan!")
\```
```

支持 200+ 编程语言的语法高亮。

## 表格

```markdown
| 列 1 | 列 2 | 列 3 |
|------|------|------|
| 数据 1 | 数据 2 | 数据 3 |
| 数据 4 | 数据 5 | 数据 6 |
```

## 数学公式

### 行内公式

```markdown
$E = mc^2$
```

### 块级公式

```markdown
$$
f(x) = \int_{-\infty}^{\infty} e^{-x^2} dx
$$
```

## 图片

### 基本语法

```markdown
![图片描述](assets/image.png)

![图片描述](assets/image.png "图片标题")
```

思源笔记会自动将图片资源存储在 `assets/` 目录下。

### 通过脚本插入图片

当需要在现有文档中插入图片时，使用 `insert_image.py` 脚本。

#### 使用方法

```bash
# 插入本地 assets 图片
python scripts/insert_image.py "文档标题" "assets/image.svg" "图片说明"

# 插入 URL 图片
python scripts/insert_image.py "文档标题" "https://example.com/image.png" "图片说明" --url
```

#### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `doc_title` | 目标文档标题（支持部分匹配） | `"我的笔记"` |
| `image_path` | 图片路径 | `assets/diagram.svg` 或 `https://example.com/image.png` |
| `caption` | 图片说明文字（可选） | `"流程图"` |
| `--url` | 标识图片路径为 URL（可选） | `--url` |

#### 返回格式

```
成功: SUCCESS|块ID|消息
失败: ERROR|错误消息
```

#### 示例

```bash
# 插入本地 SVG 流程图
python scripts/insert_image.py "流程图示例_WebDAV" "assets/excalidraw-flowchart-20260125.svg" "用户注册流程"

# 插入网络图片
python scripts/insert_image.py "技术文档" "https://example.com/architecture.png" "系统架构图" --url
```

#### 注意事项

- 文档标题支持模糊匹配，会查找包含指定标题的文档
- 图片会插入到文档末尾
- 插入后会自动添加时间戳注释
- URL 图片不会下载到本地，直接使用原始链接

## Excalidraw 图表

当需要创建图表、流程图、思维导图、架构图或可视化内容时，**优先调用 `siyuan-excalidraw` skill** 进行绘图。

### 工作流程

1. **调用绘图 skill**：使用 `siyuan-excalidraw` skill 生成图表
2. **获取返回路径**：skill 会将 SVG 保存到指定路径并返回资源路径
3. **插入图片**：使用 Markdown 图片语法插入图表

### 图片语法

```markdown
![图表描述](返回的资源路径 "图表名称")
```

示例：
```markdown
![用户注册流程](assets/excalidraw-用户注册流程-20260125171200.svg "用户注册流程")
```

### 注意事项

- Excalidraw 图表默认保存为 SVG 格式
- 资源路径可以是本地路径或 WebDAV 远程路径
- siyuan-excalidraw skill 会自动处理路径选择和文件保存

## 链接

```markdown
[链接文本](https://example.com)
[链接文本](path/to/file.md)
```

## 分割线

```markdown
---
```

或

```markdown
***
```

## 脚注

```markdown
这是一段文本[^1]

[^1]: 这是脚注内容
```

## 思源笔记特有功能

### 块缩放聚焦

所有块都支持聚焦编辑，提高写作专注度。

### 面包屑导航

在上下文中轻松切换文档路径。

### 大纲列表

支持多层级列表折叠。

### 横向排版

支持块的横向排列，适合并排显示多个内容块。

## 完整示例

```markdown
# 思源笔记示例文档

这是一篇关于思源笔记的示例文档。

## 维基链接示例

你可以链接到 [[技术笔记]] 或 [[项目计划|我的项目计划]]。

也可以引用特定的块：((20250125000000-1a2b3c4d))

## 嵌入和引用

> 这是一段引用块，可以 ((嵌入其他块))

## 列表示例

### 任务清单
- [ ] 学习思源笔记基本语法
- [x] 安装思源笔记
- [ ] 创建第一个笔记

### 项目清单
1. 需求分析
2. 系统设计
3. 开发实现
4. 测试上线

## 代码示例

```python
# 思源笔记 API 示例
import requests

def create_block(content):
    url = "http://localhost:6806/api/block/insertBlock"
    data = {
        "dataType": "markdown",
        "data": content,
        "previousID": ""
    }
    response = requests.post(url, json=data)
    return response.json()
```

## 表格示例

| 功能 | 描述 | 快捷键 |
|------|------|--------|
| 双向链接 | 文档间的相互链接 | `[[` |
| 块引用 | 引用任意内容块 | `((` |
| 属性面板 | 查看和编辑属性 | `Alt + P` |

## 数学公式

质能方程：$E = mc^2$

高斯积分：
$$
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
$$

## 标签示例

#思源笔记 #知识管理 #双链

## 参考资源

- 思源笔记官网：https://b3log.org/siyuan/
- 思源笔记 GitHub：https://github.com/siyuan-note/siyuan
```

## 注意事项

1. **块 ID**：思源笔记会自动为每个块分配唯一的 ID，格式为 `日期时间-随机字符`
2. **资源路径**：图片等资源默认存储在 `assets/` 目录下
3. **Markdown 兼容性**：思源笔记支持导出标准 Markdown，但双向链接等特性在标准 Markdown 中无法体现
4. **版本兼容**：思源笔记的 .sy.zip 格式包含所有资源和元数据，用于完整备份

## 参考

- [思源笔记官方文档](https://b3log.org/siyuan/)
- [思源笔记 GitHub 仓库](https://github.com/siyuan-note/siyuan)
- [思源笔记 API 文档](https://b3log.org/siyuan/zh-Hans/api/)
