---
name: siyuan-excalidraw
description: Excalidraw 图表生成器，为思源笔记创建流程图、思维导图、架构图等可视化内容，自动保存 SVG 到思源资源目录。当需要"绘图"、"画流程图"、"创建架构图"、"可视化"时使用此技能（应用层，依赖 siyuan 基础知识）。
metadata:
  version: 2.0.0
---

# 思源笔记 Excalidraw 图表生成器

为思源笔记生成 Excalidraw 风格的图表，直接输出 SVG 文件并自动保存到思源笔记资源目录。

## 工作流程

1. **分析内容** - 识别概念、关系、层次结构
2. **选择图表类型** - 根据内容特性选择最佳可视化形式
3. **生成 SVG** - 创建 Excalidraw 风格的 SVG 图表
4. **保存文件** - 自动保存到思源笔记资源目录
5. **返回路径** - 提供可直接在思源笔记中使用的资源路径

## 配置文件读取

**必须首先读取 `siyuan.json` 配置文件**，获取保存路径信息：

```json
{
    "local_path": "本地路径（优先使用）",
    "remote_path": {
        "webdav": true,
        "url": "WebDAV 服务器地址",
        "username": "用户名",
        "password": "密码",
        "assets_path": "资源目录路径"
    }
}
```

### 路径选择规则

1. **优先使用 `local_path`**：如果 `local_path` 非空，直接保存到该路径下的 `data/assets/` 目录
2. **备选使用 `remote_path`**：如果 `local_path` 为空，通过 WebDAV 上传到 `remote_path.assets_path`

## 图表类型选择指南

根据内容特性选择最合适的图表形式：

| 类型 | 英文 | 使用场景 | 设计要点 |
|------|------|---------|----------|
| **流程图** | Flowchart | 步骤说明、工作流程、任务执行顺序 | 箭头连接步骤，清晰表达流程走向 |
| **思维导图** | Mind Map | 概念发散、主题分类、灵感捕捉 | 中心向外发散，放射状结构 |
| **层级图** | Hierarchy | 组织结构、内容分级、系统拆解 | 自上而下或自左至右的层级节点 |
| **关系图** | Relationship | 要素影响、依赖、互动关系 | 图形间用连线表示关联 |
| **对比图** | Comparison | 方案或观点对照分析 | 左右两栏或表格形式 |
| **时间线图** | Timeline | 事件发展、项目进度 | 以时间为轴，标出关键时间点 |
| **矩阵图** | Matrix | 双维度分类、优先级定位 | X/Y 两个维度的坐标平面 |
| **自由布局** | Freeform | 零散内容、灵感记录 | 无结构限制，自由放置 |

## SVG 输出格式

### 文件命名规范

格式：`excalidraw-[主题]-[时间戳].svg`

示例：
- `excalidraw-系统架构-20260125171200.svg`
- `excalidraw-用户注册流程-20260125171200.svg`
- `excalidraw-商业模式-20260125171200.svg`

### SVG 结构模板

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" 
     viewBox="0 0 1200 800" 
     width="1200" 
     height="800"
     style="background-color: #ffffff;">
  
  <!-- Excalidraw 风格定义 -->
  <defs>
    <!-- 手绘风格滤镜 -->
    <filter id="roughness">
      <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" result="noise"/>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="1" xChannelSelector="R" yChannelSelector="G"/>
    </filter>
    
    <!-- 箭头标记 -->
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#1e1e1e"/>
    </marker>
    
    <!-- 手写字体样式 -->
    <style>
      .excalidraw-text {
        font-family: "Virgil", "Segoe UI Emoji", "Apple Color Emoji", sans-serif;
        font-size: 20px;
        fill: #1e1e1e;
      }
      .excalidraw-title {
        font-family: "Virgil", "Segoe UI Emoji", "Apple Color Emoji", sans-serif;
        font-size: 28px;
        font-weight: bold;
        fill: #1e40af;
      }
      .excalidraw-subtitle {
        font-family: "Virgil", "Segoe UI Emoji", "Apple Color Emoji", sans-serif;
        font-size: 20px;
        fill: #3b82f6;
      }
      .excalidraw-body {
        font-family: "Virgil", "Segoe UI Emoji", "Apple Color Emoji", sans-serif;
        font-size: 16px;
        fill: #374151;
      }
    </style>
  </defs>
  
  <!-- 图表内容区域 -->
  <g id="content">
    <!-- 在此处添加图表元素 -->
  </g>
  
</svg>
```

## 设计规范

### 颜色方案

| 用途 | 颜色代码 | 说明 |
|------|----------|------|
| 标题 | `#1e40af` | 深蓝色 |
| 副标题/连接线 | `#3b82f6` | 亮蓝色 |
| 正文文字 | `#374151` | 深灰色 |
| 强调/重点 | `#f59e0b` | 金色 |
| 成功/完成 | `#10b981` | 绿色 |
| 警告/注意 | `#ef4444` | 红色 |
| 边框/线条 | `#1e1e1e` | 黑色 |
| 背景填充 | `#f3f4f6` | 浅灰色 |
| 画布背景 | `#ffffff` | 白色 |

### 字体大小规范

- **标题**：24-28px
- **副标题**：18-20px
- **正文/说明**：14-16px
- **标注/小字**：12px

### 布局规范

- **画布尺寸**：1200 x 800 像素（可根据内容调整）
- **边距**：四周保留 40-60px 边距
- **元素间距**：相邻元素间保持 20-40px 间距
- **对齐方式**：使用网格对齐，保持视觉整洁

### Excalidraw 手绘风格要点

1. **线条**：略带不规则，模拟手绘效果
2. **圆角**：矩形使用圆角（rx="8"）
3. **填充**：使用半透明或斜线填充
4. **阴影**：轻微的投影效果增加层次感

## SVG 元素模板

### 矩形框（节点）

```xml
<g class="node">
  <rect x="100" y="100" width="200" height="60" 
        rx="8" ry="8"
        fill="#f3f4f6" 
        stroke="#1e1e1e" 
        stroke-width="2"/>
  <text x="200" y="135" text-anchor="middle" class="excalidraw-text">节点文本</text>
</g>
```

### 椭圆（起止点）

```xml
<g class="terminal">
  <ellipse cx="200" cy="100" rx="80" ry="40"
           fill="#e0f2fe"
           stroke="#1e1e1e"
           stroke-width="2"/>
  <text x="200" y="105" text-anchor="middle" class="excalidraw-text">开始</text>
</g>
```

### 菱形（判断）

```xml
<g class="decision">
  <polygon points="200,50 280,100 200,150 120,100"
           fill="#fef3c7"
           stroke="#1e1e1e"
           stroke-width="2"/>
  <text x="200" y="105" text-anchor="middle" class="excalidraw-text">条件?</text>
</g>
```

### 箭头连接线

```xml
<line x1="300" y1="130" x2="400" y2="130"
      stroke="#1e1e1e"
      stroke-width="2"
      marker-end="url(#arrowhead)"/>
```

### 曲线箭头

```xml
<path d="M 100 100 Q 150 50 200 100"
      fill="none"
      stroke="#1e1e1e"
      stroke-width="2"
      marker-end="url(#arrowhead)"/>
```

### 虚线连接

```xml
<line x1="100" y1="100" x2="200" y2="100"
      stroke="#3b82f6"
      stroke-width="2"
      stroke-dasharray="8,4"/>
```

## 完整示例

### 示例 1：简单流程图

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" width="800" height="400" style="background-color: #ffffff;">
  <defs>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#1e1e1e"/>
    </marker>
    <style>
      .excalidraw-text { font-family: "Virgil", sans-serif; font-size: 16px; fill: #1e1e1e; }
      .excalidraw-title { font-family: "Virgil", sans-serif; font-size: 24px; fill: #1e40af; font-weight: bold; }
    </style>
  </defs>
  
  <!-- 标题 -->
  <text x="400" y="40" text-anchor="middle" class="excalidraw-title">用户注册流程</text>
  
  <!-- 开始 -->
  <ellipse cx="100" cy="200" rx="60" ry="30" fill="#e0f2fe" stroke="#1e1e1e" stroke-width="2"/>
  <text x="100" y="205" text-anchor="middle" class="excalidraw-text">开始</text>
  
  <!-- 箭头 -->
  <line x1="160" y1="200" x2="220" y2="200" stroke="#1e1e1e" stroke-width="2" marker-end="url(#arrowhead)"/>
  
  <!-- 步骤1 -->
  <rect x="230" y="170" width="120" height="60" rx="8" fill="#f3f4f6" stroke="#1e1e1e" stroke-width="2"/>
  <text x="290" y="205" text-anchor="middle" class="excalidraw-text">填写信息</text>
  
  <!-- 箭头 -->
  <line x1="350" y1="200" x2="410" y2="200" stroke="#1e1e1e" stroke-width="2" marker-end="url(#arrowhead)"/>
  
  <!-- 判断 -->
  <polygon points="490,140 560,200 490,260 420,200" fill="#fef3c7" stroke="#1e1e1e" stroke-width="2"/>
  <text x="490" y="205" text-anchor="middle" class="excalidraw-text">验证?</text>
  
  <!-- 箭头 -->
  <line x1="560" y1="200" x2="620" y2="200" stroke="#1e1e1e" stroke-width="2" marker-end="url(#arrowhead)"/>
  
  <!-- 结束 -->
  <ellipse cx="700" cy="200" rx="60" ry="30" fill="#d1fae5" stroke="#1e1e1e" stroke-width="2"/>
  <text x="700" y="205" text-anchor="middle" class="excalidraw-text">完成</text>
</svg>
```

### 示例 2：思维导图

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600" width="1000" height="600" style="background-color: #ffffff;">
  <defs>
    <style>
      .center { font-family: "Virgil", sans-serif; font-size: 24px; fill: #1e40af; font-weight: bold; }
      .branch { font-family: "Virgil", sans-serif; font-size: 18px; fill: #3b82f6; }
      .leaf { font-family: "Virgil", sans-serif; font-size: 14px; fill: #374151; }
    </style>
  </defs>
  
  <!-- 中心节点 -->
  <ellipse cx="500" cy="300" rx="100" ry="50" fill="#dbeafe" stroke="#1e40af" stroke-width="3"/>
  <text x="500" y="305" text-anchor="middle" class="center">核心主题</text>
  
  <!-- 分支1 -->
  <line x1="600" y1="280" x2="750" y2="150" stroke="#3b82f6" stroke-width="2"/>
  <rect x="720" y="120" width="120" height="50" rx="25" fill="#f0f9ff" stroke="#3b82f6" stroke-width="2"/>
  <text x="780" y="150" text-anchor="middle" class="branch">分支一</text>
  
  <!-- 分支2 -->
  <line x1="600" y1="320" x2="750" y2="450" stroke="#3b82f6" stroke-width="2"/>
  <rect x="720" y="430" width="120" height="50" rx="25" fill="#f0f9ff" stroke="#3b82f6" stroke-width="2"/>
  <text x="780" y="460" text-anchor="middle" class="branch">分支二</text>
  
  <!-- 分支3 -->
  <line x1="400" y1="280" x2="250" y2="150" stroke="#3b82f6" stroke-width="2"/>
  <rect x="160" y="120" width="120" height="50" rx="25" fill="#f0f9ff" stroke="#3b82f6" stroke-width="2"/>
  <text x="220" y="150" text-anchor="middle" class="branch">分支三</text>
  
  <!-- 分支4 -->
  <line x1="400" y1="320" x2="250" y2="450" stroke="#3b82f6" stroke-width="2"/>
  <rect x="160" y="430" width="120" height="50" rx="25" fill="#f0f9ff" stroke="#3b82f6" stroke-width="2"/>
  <text x="220" y="460" text-anchor="middle" class="branch">分支四</text>
</svg>
```

## 实现步骤

### 步骤 1：生成 SVG 内容

根据用户需求分析内容，选择合适的图表类型，生成 SVG 代码。

### 步骤 2：调用上传脚本

使用提供的 `upload_asset.py` 脚本上传 SVG 文件：

```python
import subprocess
import json

# 步骤 2.1：调用上传脚本
result = subprocess.run([
    'python', 'scripts/upload_asset.py', svg_content, topic
], capture_output=True, text=True)

# 步骤 2.2：解析返回结果
if result.returncode == 0:
    # 返回格式：ASSET_PATH|资源路径|消息
    _, asset_path, message = result.stdout.strip().split('|', 2)
    print(f"✅ {message}")
    print(f"📍 资源路径：{asset_path}")
else:
    # 返回格式：ERROR|错误消息
    error_msg = result.stdout.strip().split('|', 1)[1]
    print(f"❌ {error_msg}")
```

### 步骤 3：返回资源路径

```python
# 返回思源笔记可用的 Markdown 图片引用
print(f"\n📖 在思源笔记中使用：")
print(f"![图表描述]({asset_path})")
```

## 输出确认模板

生成图表后，向用户报告：

```
✅ Excalidraw 图表已生成！

📍 保存位置：
assets/excalidraw-[主题]-[时间戳].svg

🎨 图表说明：
- 图表类型：[所选类型]
- 选择原因：[为什么选择这种类型]
- 包含元素：[主要内容概述]

📖 在思源笔记中使用：
在文档中插入以下 Markdown：
![图表描述](assets/excalidraw-[主题]-[时间戳].svg)

或者直接拖放 SVG 文件到编辑器中。

需要调整吗？比如修改布局、添加元素、调整配色？
```

## 注意事项

1. **字体兼容性**：SVG 使用 Virgil 字体模拟 Excalidraw 手写风格，如系统未安装会回退到 sans-serif
2. **文件大小**：保持 SVG 简洁，避免过于复杂的路径
3. **编码格式**：始终使用 UTF-8 编码
4. **思源笔记兼容**：生成的 SVG 可直接在思源笔记中显示
5. **WebDAV 安全**：上传时使用 HTTPS（如可用）

## 依赖环境

运行 `upload_asset.py` 脚本需要以下环境：

### Python 环境

- Python 3.6 或更高版本
- requests 库

### 安装依赖

```bash
# 安装 requests 库
pip install requests
```

### 配置文件

确保 `siyuan.json` 文件存在于项目根目录，包含以下字段：

```json
{
    "local_path": "本地路径（优先使用）",
    "remote_path": {
        "webdav": true,
        "url": "WebDAV 服务器地址",
        "username": "用户名",
        "password": "密码",
        "assets_path": "资源目录路径"
    }
}
```

## upload_asset.py 脚本说明

`upload_asset.py` 是专门为思源笔记 Excalidraw 资源上传设计的脚本，功能如下：

### 主要功能

1. **自动选择保存方式**：根据 `siyuan.json` 配置，优先使用本地保存，备选 WebDAV 上传
2. **生成文件名**：自动生成带时间戳的文件名，避免冲突
3. **路径规范化**：自动处理路径格式，确保与思源笔记兼容
4. **错误处理**：完善的异常处理和友好的错误提示

### 使用方法

#### 命令行使用

```bash
python scripts/upload_asset.py <svg_content> <topic>
```

参数说明：
- `svg_content`: SVG 内容（需用引号包裹）
- `topic`: 图表主题

示例：

```bash
python scripts/upload_asset.py "<?xml version='1.0'...?>" "系统架构"
```

#### 作为模块使用

```python
from scripts.upload_asset import upload_asset

success, asset_path, message = upload_asset(svg_content, "系统架构")

if success:
    print(f"✅ {message}")
    print(f"📍 资源路径：{asset_path}")
else:
    print(f"❌ {message}")
```

### 返回格式

脚本的标准输出格式如下：

#### 成功

```
ASSET_PATH|assets/excalidraw-系统架构-20260125171200.svg|已保存到本地: /path/to/siyuan/data/assets/excalidraw-系统架构-20260125171200.svg
```

#### 失败

```
ERROR|上传失败: WebDAV 连接超时
```

### 路径选择逻辑

1. **检查 `local_path`**：如果 `local_path` 非空且有效，直接保存到本地
   - 保存路径：`{local_path}/data/assets/{filename}`

2. **使用 WebDAV**：如果 `local_path` 为空，检查 `remote_path.webdav`
   - 上传 URL：`{remote_path.url}/{remote_path.assets_path}{filename}`
   - 使用 Basic Authentication 进行认证

3. **失败处理**：如果两者都不可用，返回错误信息

### 配置补充说明

- `local_path` 应指向思源工作目录根目录，而不是 `assets` 目录本身
- 如果思源运行在 Docker 中，只有当脚本也运行在容器内时才应填写容器路径；否则请填写宿主机挂载路径
- 不使用 WebDAV 时，只保留 `local_path` 即可；`remote_path.webdav` 可设为 `false`

### WebDAV 上传详情

脚本使用 Python `requests` 库进行 WebDAV 上传：

- HTTP 方法：PUT
- 认证方式：Basic Authentication
- Content-Type：`image/svg+xml`
- 超时时间：30 秒

### 依赖要求

```bash
pip install requests
```

## 参考资源

- [Excalidraw 官网](https://excalidraw.com/)
- [SVG 规范](https://www.w3.org/TR/SVG2/)
- [思源笔记官网](https://b3log.org/siyuan/)
- [思源笔记 API 文档](https://b3log.org/siyuan/zh-Hans/api/)
