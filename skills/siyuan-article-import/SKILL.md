---
name: siyuan-article-import
description: 文章导入专用工具，从网络抓取文章（微信公众号、知乎、掘金、博客等）并导入思源笔记。自动处理图片下载、内容格式化和文档创建。当需要"导入文章"、"保存网页"、"抓取内容"时使用此技能（应用层，依赖 siyuan 基础知识）。
triggers:
  - 导入文章
  - 保存文章
  - 微信文章
  - 公众号文章
  - 网页文章
  - 文章转笔记
  - URL 导入
  - 抓取文章
version: 2.0.0
tags: [siyuan, article-import, wechat, web-scraper]
---

# 通用文章导入 Skill

从各种来源（微信公众号、知乎、掘金、博客等）抓取文章并导入到思源笔记。

## 快速开始

### 基本用法

```bash
# 导入单篇文章
python scripts/import_article.py <文章URL>

# 指定笔记本
python scripts/import_article.py <文章URL> <笔记本名称>
```

### 处理图片

```python
import subprocess

# 上传单张图片
result = subprocess.run([
    'python', 'scripts/upload_image.py',
    'https://example.com/image.jpg', '图片描述'
], capture_output=True, text=True)

if result.returncode == 0:
    _, asset_path, _ = result.stdout.strip().split('|', 2)
    print(f"资源路径：{asset_path}")
```

## 支持的文章来源

| 来源 | 域名 | 特殊处理 |
|-----|------|---------|
| 微信公众号 | mp.weixin.qq.com | 图片必须下载 |
| 知乎专栏 | zhuanlan.zhihu.com | 移除推荐内容 |
| 掘金 | juejin.cn | 处理代码块 |
| 其他博客 | 任意 URL | 检查防盗链 |

## 核心特性

### 1. 自动图片处理

网络图片（尤其是微信）不能直接在思源显示，会自动：
- 下载到临时目录
- 上传到思源资源库
- 替换为本地路径
- 清理临时文件

### 2. 防止重复导入

创建文档前自动检查是否已存在，避免重复。

### 3. 默认笔记本

网络文章统一存入 `知识储备` 笔记本，自动创建。

## 关键约束

### Windows 环境乱码问题

**重要：Windows 下必须使用 Python 脚本调用 API，避免 curl 中文乱码**

```python
# ✅ 正确
response = requests.post(
    f'{api_url}/api/filetree/createDocWithMd?token={token}',
    json={'notebook': nb_id, 'path': '/标题', 'markdown': content}
)

# ❌ 错误（会产生乱码）
curl -X POST "..." -d '{"markdown": "中文内容"}'
```

### 文档命名规范

使用简单字符，避免特殊符号：

```
✅ /技术文章-20250125
✅ /RDL技术详解
❌ /标题：包含@#$特殊字符
```

## 参考文档

- **API 参考**：[references/api.md](references/api.md) - 思源 API 详细文档
- **图片处理**：[references/image-processing.md](references/image-processing.md) - 图片处理最佳实践
- **工作流程**：[references/workflows.md](references/workflows.md) - 完整导入流程和实现细节

## 配置文件

推荐在仓库根目录放置 `.claude/siyuan.json`（也兼容根目录 `siyuan.json`）：

```json
{
    "api_url": "http://127.0.0.1:6806",
    "api_token": "your-api-token",
    "local_path": "/path/to/siyuan/workspace"
}
```

- `local_path` 应指向思源工作目录根目录，资源会保存到 `{local_path}/data/assets/`
- 如果思源在 Docker 中而脚本在宿主机执行，`local_path` 应填写宿主机挂载路径，而不是容器内路径
- 不使用 WebDAV 时，`remote_path` 可以省略，或保留但设置 `webdav: false`

## 常见问题

**Q: 图片无法显示？**
A: 使用 `upload_image.py` 下载上传，详见 [图片处理参考](references/image-processing.md)

**Q: 如何验证文档创建成功？**
A: 使用 SQL 查询验证，详见 [API 参考](references/api.md)

**Q: 如何避免重复创建文档？**
A: 创建前检查函数，详见 [工作流程](references/workflows.md)
