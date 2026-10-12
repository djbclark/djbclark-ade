# 思源笔记 API 参考

本文档提供思源笔记 API 的详细参考信息。

## API 基础

### 请求格式

所有 API 请求都需要 `token` 参数进行认证。

```python
import requests

api_url = 'http://127.0.0.1:6806'
token = 'your-api-token'

# GET 请求示例
response = requests.get(f'{api_url}/api/system/version?token={token}')

# POST 请求示例
response = requests.post(
    f'{api_url}/api/filetree/createDocWithMd?token={token}',
    json={'notebook': notebook_id, 'path': '/文档标题', 'markdown': content},
    headers={'Content-Type': 'application/json'}
)
```

### 输出格式规范

#### 成功输出
```
SUCCESS|<文档ID>|<描述信息>
SUCCESS|20260125123456-abc123|文档创建成功
```

#### 错误输出
```
ERROR|<错误信息>|额外信息
ERROR|配置文件未找到|
ERROR|API认证失败|
```

## 核心 API 端点

### 1. 笔记本管理

#### 列出所有笔记本
```python
response = requests.get(f'{api_url}/api/notebook/listNotebooks?token={token}')
notebooks = response.json().get('data', {}).get('notebooks', [])
```

#### 创建笔记本
```python
response = requests.post(
    f'{api_url}/api/notebook/createNoteBook?token={token}',
    json={'name': notebook_name, 'icon': ''},
    headers={'Content-Type': 'application/json'}
)
result = response.json()
if result.get('code') == 0:
    notebook_id = result['data']['notebook']['id']
```

### 2. 文档管理

#### 创建文档（使用 Markdown）
```python
response = requests.post(
    f'{api_url}/api/filetree/createDocWithMd?token={token}',
    json={
        'notebook': notebook_id,
        'path': '/文档标题',
        'markdown': markdown_content
    },
    headers={'Content-Type': 'application/json'}
)
result = response.json()
if result.get('code') == 0:
    doc_id = result['data']
```

#### 检查文档是否存在
```python
def check_document_exists(notebook_id, title):
    """检查文档是否已存在"""
    safe_title = title.replace("'", "''")
    query = f"""
    SELECT id, root_id
    FROM blocks
    WHERE type = 'd'
      AND content = '{safe_title}'
      AND box = '{notebook_id}'
    LIMIT 1
    """

    response = requests.post(
        f"{api_url}/api/query/sql?token={token}",
        json={'stmt': query}
    )

    result = response.json()
    if result.get('code') == 0:
        data = result.get('data', [])
        if len(data) > 0:
            return data[0][0]  # 返回文档ID
    return None
```

### 3. SQL 查询

#### 执行查询
```python
query = "SELECT * FROM blocks WHERE type = 'd'"
response = requests.post(
    f'{api_url}/api/query/sql?token={token}',
    json={'stmt': query}
)
```

## 配置文件格式

### siyuan.json 结构

```json
{
    "api_url": "http://127.0.0.1:6806",
    "api_token": "your-api-token",
    "local_path": "/path/to/siyuan/workspace",
    "remote_path": {
        "webdav": true,
        "url": "https://your-webdav-server.com",
        "username": "username",
        "password": "password",
        "assets_path": "/assets"
    }
}
```

### 加载配置文件

```python
import json
from pathlib import Path

def load_config():
    """加载配置文件，支持多个位置"""
    possible_paths = [
        Path(__file__).parent.parent.parent / '.claude' / 'siyuan.json',  # .claude 目录
        Path(__file__).parent.parent / 'siyuan.json',  # 项目根目录
        Path(__file__).parent / 'siyuan.json',  # 当前目录
    ]

    for config_file in possible_paths:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    return None
```

## 常见错误处理

### 连接中断处理

当文档内容较大时，思源 API 可能会断开连接：

```python
def verify_document_created(notebook_id, title):
    """通过查询验证文档是否创建成功"""
    query = f"""
    SELECT id, root_id
    FROM blocks
    WHERE type = 'd'
      AND content = '{title}'
      AND box = '{notebook_id}'
    ORDER BY created DESC
    LIMIT 1
    """

    response = requests.post(
        f"{api_url}/api/query/sql?token={token}",
        json={'stmt': query},
        timeout=30
    )

    result = response.json()
    if result.get('code') == 0:
        data = result.get('data', [])
        if len(data) > 0:
            return {'root_id': data[0]['root_id']}
    return None

# 在 create_document 中使用
def create_document(notebook_id, title, content):
    response = requests.post(...)

    try:
        result = response.json()
        # 正常处理
    except Exception:
        # JSON 解析失败，尝试验证文档是否创建成功
        return verify_document_created(notebook_id, title)
```

## 相关资源

- [思源笔记 API 官方文档](https://b3log.org/siyuan/zh-Hans/api/)
- [思源笔记 SQL 查询文档](https://b3log.org/siyuan/zh-Hans/api/query/sql.html)
