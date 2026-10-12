# 思源笔记 API 交互指南

## API 概述

思源笔记提供了一套 RESTful API，支持与外部系统进行数据交互。

- **默认服务地址**：`http://127.0.0.1:6806`
- **请求方法**：所有 API 使用 POST 方法
- **数据格式**：请求和响应均为 JSON 格式
- **完整文档**：[GitHub 官方文档](https://github.com/siyuan-note/siyuan)

## 认证

如果思源笔记开启了 API Token 认证，需要在请求头中携带 Token：

```bash
curl -X POST http://127.0.0.1:6806/api/xxx \
  -H "Content-Type: application/json" \
  -H "Authorization: Token YOUR_API_TOKEN" \
  -d '{"key": "value"}'
```

> 💡 **提示**：API Token 在思源笔记设置 → 关于 → API Token 中获取或设置。

## 常用 API 端点分类

### 内容块操作 `/api/block/*`

| 端点 | 描述 |
|------|------|
| /api/block/getBlockKramdown | 获取块 Kramdown 源码 |
| /api/block/insertBlock | 插入块 |
| /api/block/updateBlock | 更新块 |
| /api/block/deleteBlock | 删除块 |
| /api/block/moveBlock | 移动块 |
| /api/block/appendBlock | 追加块 |
| /api/block/prependBlock | 前置块 |
| /api/block/getChildBlocks | 获取子块 |
| /api/block/transferBlockRef | 转移块引用 |

### 文档树操作 `/api/filetree/*`

| 端点 | 描述 |
|------|------|
| /api/filetree/createDocWithMd | 使用 Markdown 创建文档 |
| /api/filetree/renameDoc | 重命名文档 |
| /api/filetree/removeDoc | 删除文档 |
| /api/filetree/moveDocs | 移动文档 |
| /api/filetree/getHPathByPath | 根据路径获取人类可读路径 |
| /api/filetree/getHPathByID | 根据 ID 获取人类可读路径 |

### 文件操作 `/api/file/*`

| 端点 | 描述 |
|------|------|
| /api/file/getFile | 获取文件内容 |
| /api/file/putFile | 上传/写入文件 |
| /api/file/removeFile | 删除文件 |
| /api/file/renameFile | 重命名文件 |
| /api/file/readDir | 读取目录 |

### SQL 查询 `/api/query/*`

| 端点 | 描述 |
|------|------|
| /api/query/sql | 执行 SQL 查询 |

### 属性操作 `/api/attr/*`

| 端点 | 描述 |
|------|------|
| /api/attr/setBlockAttrs | 设置块属性 |
| /api/attr/getBlockAttrs | 获取块属性 |

## curl 调用示例

### SQL 查询

```bash
curl -X POST http://127.0.0.1:6806/api/query/sql \
  -H "Content-Type: application/json" \
  -d '{"stmt": "SELECT * FROM blocks WHERE type=\"d\" LIMIT 10"}'
```

### 插入块

```bash
curl -X POST http://127.0.0.1:6806/api/block/insertBlock \
  -H "Content-Type: application/json" \
  -d '{
    "dataType": "markdown",
    "data": "# 新标题\n\n这是内容",
    "parentID": "父块ID"
  }'
```

### 设置块属性

```bash
curl -X POST http://127.0.0.1:6806/api/attr/setBlockAttrs \
  -H "Content-Type: application/json" \
  -d '{
    "id": "块ID",
    "attrs": {
      "custom-priority": "high",
      "custom-status": "doing"
    }
  }'
```

### 获取文件

```bash
curl -X POST http://127.0.0.1:6806/api/file/getFile \
  -H "Content-Type: application/json" \
  -d '{"path": "/data/20210808180117-6v0mkxr/20210808180117-czj9bvb.sy"}'
```

## 响应格式

所有 API 的响应遵循统一格式：

```json
{
  "code": 0,
  "msg": "",
  "data": { ... }
}
```

- `code`: 0 表示成功，非 0 表示错误
- `msg`: 错误信息或提示信息
- `data`: 返回的具体数据

## 重要警告

### 🚨 中文编码警告（非常重要！）

> ⚠️ **禁止使用 curl 直接推送包含中文的内容**！
>
> 使用 curl 命令直接向思源笔记 API 推送中文内容会导致**乱码问题**。
>
> **错误示例**（会产生乱码）：
> ```bash
> curl -X POST "http://127.0.0.1:6806/api/filetree/createDocWithMd" \
>   -H "Authorization: Token YOUR_TOKEN" \
>   -H "Content-Type: application/json" \
>   -d '{"markdown": "这是中文内容"}'
> ```
>
> **正确做法**：使用编程语言（Python、JavaScript 等）调用 API，确保正确的 UTF-8 编码：
>
> **Python 示例**（推荐）：
> ```python
> import requests
>
> response = requests.post(
>     'http://127.0.0.1:6806/api/filetree/createDocWithMd',
>     headers={
>         'Authorization': 'Token YOUR_TOKEN',
>         'Content-Type': 'application/json'
>     },
>     json={
>         'notebook': '笔记本ID',
>         'path': '/文档路径',
>         'markdown': '这是中文内容，编码正常'
>     }
> )
> ```
>
> **Node.js 示例**：
> ```javascript
> const response = await fetch('http://127.0.0.1:6806/api/filetree/createDocWithMd', {
>     method: 'POST',
>     headers: {
>         'Authorization': 'Token YOUR_TOKEN',
>         'Content-Type': 'application/json'
>     },
>     body: JSON.stringify({
>         notebook: '笔记本ID',
>         path: '/文档路径',
>         markdown: '这是中文内容，编码正常'
>     })
> });
> ```

### 文件操作警告

> ⚠️ **警告**：插件或外部扩展如果需要读取或写入 `data` 目录下的文件，**请通过调用内核 API 来实现**，不要自行调用 `fs` 或其他 Node.js API，否则可能导致数据同步时分块丢失，造成云端数据损坏。
>
> 请使用 `/api/file/*` 系列 API（如 `/api/file/getFile`、`/api/file/putFile`）。

## 日记文档属性

思源笔记在创建日记时会自动添加 `custom-dailynote-yyyymmdd` 属性，用于将日记文档与普通文档区分。

如果手动创建日记文档（如使用 `createDocWithMd` API），请手动添加该属性，例如：

```json
{
  "custom-dailynote-20250125": "20250125"
}
```

## 相关资源

- [思源笔记 GitHub 仓库](https://github.com/siyuan-note/siyuan)
- [完整 API 文档](https://github.com/siyuan-note/siyuan/blob/master/API_zh_CN.md)
- [SQL 查询文档](https://github.com/siyuan-note/siyuan/blob/master/SQL_zh_CN.md)
