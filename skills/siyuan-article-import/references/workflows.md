# 文章导入工作流程

本文档详细说明文章导入的完整工作流程和实现细节。

## 完整导入流程

### 1. 获取文章内容

使用 web-reader MCP 工具获取文章 Markdown 内容：

```python
from mcp_web_reader import webReader

result = webReader(
    url="https://mp.weixin.qq.com/s/xxx",
    return_format="markdown",
    retain_images=True,
    with_images_summary=True
)
```

### 2. 处理图片链接

**重要**：检查图片来源，决定是否需要下载

- 微信图片：必须下载后上传
- 其他图片：尝试直接使用，失败则下载
- 遍历文章中所有 `![](http...)` 格式的图片
- 使用 `upload_image.py` 脚本处理需要下载的图片
- 替换为本地资源路径：`assets/img-xxx-20250125.png`

### 3. 整理内容结构

- 添加元信息块（来源、作者、链接、导入时间）
- 规范化标题层级
- 移除无用的广告和推荐内容
- 添加表格格式化列表内容

### 4. 创建笔记

- 使用 Python 脚本调用 API
- 创建前检查文档是否已存在
- 避免中文路径和特殊字符
- 输出结构化结果

## 检测文章来源

```python
import urllib.parse

def detect_article_source(url):
    """
    检测文章来源

    Returns:
        str: 来源类型 (wechat, zhihu, juejin, generic)
    """
    parsed = urllib.parse.urlparse(url)

    if 'mp.weixin.qq.com' in parsed.netloc:
        return 'wechat'
    elif 'zhuanlan.zhihu.com' in parsed.netloc:
        return 'zhihu'
    elif 'juejin.cn' in parsed.netloc:
        return 'juejin'
    else:
        return 'generic'
```

## 不同来源的特殊处理

| 来源 | 特殊处理 | 注意事项 |
|-----|---------|---------|
| **微信公众号** | 图片必须下载上传 | 链接可能带有 blob:// |
| **知乎** | 移除推荐内容 | 注意登录墙问题 |
| **掘金** | 处理代码块 | 代码格式可能需要调整 |
| **个人博客** | 检查图片防盗链 | 可能需要自定义 User-Agent |

## 默认笔记本约定

**约定**：所有从网络导入的文章统一存入 `知识储备` 笔记本中。

### 实现方式

```python
# 查找或创建"知识储备"笔记本
fragment_notebook = next((nb for nb in notebooks if nb['name'] == '知识储备'), None)

if fragment_notebook:
    notebook_id = fragment_notebook['id']
    notebook_name = fragment_notebook['name']
else:
    # 创建"知识储备"笔记本
    notebook_id = create_notebook('知识储备')
    notebook_name = '知识储备'
```

### 创建笔记本函数

```python
def create_notebook(name):
    """创建笔记本"""
    config = load_config()
    if not config:
        print('ERROR|配置文件未找到|')
        return None

    response = requests.post(
        f"{config['api_url'].rstrip('/')}/api/notebook/createNoteBook?token={config['api_token']}",
        json={'name': name, 'icon': ''},
        headers={'Content-Type': 'application/json'},
        timeout=30
    )

    result = response.json()
    if result.get('code') == 0:
        notebook_id = result['data']['notebook']['id']
        print(f'SUCCESS|{notebook_id}|笔记本创建成功: {name}')
        return notebook_id
    else:
        print(f"ERROR|{result.get('msg', '创建笔记本失败')}|")
        return None
```

## 创建或更新文档

```python
def create_or_update_document(notebook_id, title, content):
    """
    创建或更新文档

    Args:
        notebook_id: 笔记本ID（建议使用"知识储备"笔记本）
        title: 文档标题
        content: Markdown内容

    Returns:
        dict: 包含 root_id 的字典，或 None

    注意：
    - 网络文章应统一存入"知识储备"笔记本
    - 使用前应先确认或创建该笔记本
    """
    config = load_config()
    if not config:
        print('ERROR|配置文件未找到|')
        return None

    # 检查文档是否已存在
    existing_id = check_document_exists(notebook_id, title)
    if existing_id:
        print(f'文档已存在: {existing_id}')
        # 可以选择更新或跳过
        # 这里选择跳过，返回已存在的文档信息
        return {'root_id': existing_id}

    # 处理图片
    print('正在处理文章中的图片...')
    processed_content = process_images(content)

    # 确保标题路径安全
    safe_title = title.replace('/', '-').replace('\\', '-').replace(':', '：')
    path = f'/{safe_title}'

    response = requests.post(
        f"{config['api_url'].rstrip('/')}/api/filetree/createDocWithMd?token={config['api_token']}",
        json={
            'notebook': notebook_id,
            'path': path,
            'markdown': processed_content
        },
        headers={'Content-Type': 'application/json'}
    )

    result = response.json()
    if result.get('code') == 0:
        # 正确处理返回值
        doc_id = result['data']
        if isinstance(doc_id, str):
            return {'root_id': doc_id}
        elif isinstance(doc_id, dict):
            return doc_id
    else:
        print(f"ERROR|{result.get('msg', '创建文档失败')}|")
        return None
```

## 文档命名规范

**重要：文档和笔记本名称使用 ASCII 或简单中文，避免特殊字符**

### 推荐命名方式
```
/技术文章-20250125
/RDL技术详解
/芯片封装技术-RDL
```

### 避免的命名方式
```
/❌ 包含emoji的标题
/标题：包含特殊字符@#$
/超长标题且包含复杂符号和全角字符
```

## 使用示例

### 完整的导入函数

```python
def import_article(url, notebook_name='知识储备'):
    """导入文章到思源笔记"""
    # 1. 检测文章来源
    source_type = detect_article_source(url)
    print(f'检测到文章来源: {source_type}')

    # 2. 加载配置
    config = load_config()
    if not config:
        print('ERROR|配置文件未找到|')
        return

    # 3. 获取或创建笔记本
    notebooks = get_notebooks()
    notebook = next((nb for nb in notebooks if nb['name'] == notebook_name), None)

    if notebook:
        notebook_id = notebook['id']
    else:
        notebook_id = create_notebook(notebook_name)

    # 4. 使用 web-reader 获取内容
    # (参考工作流程部分的示例代码)

    # 5. 处理图片
    # 6. 创建笔记
    pass

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python import_article.py <文章URL>')
        sys.exit(1)

    url = sys.argv[1]
    import_article(url)
```

## 问题排查清单

在导入文章时，使用此清单确保不遗漏关键点：

### 配置检查
- [ ] 配置文件 `siyuan.json` 存在于可访问位置
- [ ] API URL 和 Token 配置正确
- [ ] 本地路径或 WebDAV 配置完整

### 图片处理
- [ ] 支持多种图片 URL 格式（http/https）
- [ ] 跳过 blob:// 和其他无效链接
- [ ] 下载失败时有错误提示
- [ ] 上传成功后删除临时文件
- [ ] subprocess 调用使用正确的编码设置

### 文档创建
- [ ] 创建前检查文档是否已存在
- [ ] **使用 `知识储备` 笔记本存储网络文章**
- [ ] 如果笔记本不存在，自动创建
- [ ] API 调用设置合理的超时时间
- [ ] 处理 JSON 解析失败的情况
- [ ] 通过查询验证文档创建状态
- [ ] 脚本可以安全地重新运行（幂等性）

### 错误处理
- [ ] 网络错误有清晰的提示
- [ ] 文件操作失败时清理临时资源
- [ ] SQL 查询对特殊字符进行转义
- [ ] 输出使用结构化格式（SUCCESS/ERROR/WARNING）
