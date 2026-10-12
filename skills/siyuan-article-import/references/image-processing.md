# 图片处理参考

本文档详细说明文章导入过程中的图片处理流程和最佳实践。

## 为什么需要处理图片

网络文章（尤其是微信公众号）的图片链接不能直接在思源笔记中显示，原因包括：

1. **防盗链机制**：许多网站设置了图片防盗链
2. **访问限制**：某些图片需要特定的 Cookie 或 Referer 才能访问
3. **动态链接**：部分图片链接是临时的，会过期失效

## 图片处理流程

```
原始链接 → 下载图片 → 上传到思源 → 使用本地路径
```

### 使用 upload_image.py 脚本

```python
import subprocess

# 处理单张图片
result = subprocess.run([
    'python', 'scripts/upload_image.py',
    'https://mmbiz.qpic.cn/xxx/0?wx_fmt=jpeg',
    '封面图'
], capture_output=True, text=True)

if result.returncode == 0:
    # 返回格式：ASSET_PATH|资源路径|消息
    _, asset_path, message = result.stdout.strip().split('|', 2)
    print(f"✅ {message}")
    print(f"📍 资源路径：{asset_path}")
else:
    error_msg = result.stdout.strip().split('|', 1)[1]
    print(f"❌ {error_msg}")
```

## 不同来源图片的处理策略

| 来源 | 特点 | 处理方式 |
|-----|------|---------|
| **微信公众号** | 必须下载上传 | 使用 upload_image.py |
| **知乎/掘金** | 可能可直接访问 | 尝试直接使用，失败则下载 |
| **图床图片** | 通常可直接使用 | 直接使用 URL |
| **Base64 图片** | 内嵌在 HTML 中 | 需要特殊处理 |

## 检测图片是否需要下载

```python
def should_download_image(url):
    """判断图片是否需要下载到本地"""
    import urllib.parse

    # 这些域名的图片必须下载
    must_download_domains = [
        'mmbiz.qpic.cn',  # 微信
        'wx.qlogo.cn',    # 微信头像
    ]

    parsed = urllib.parse.urlparse(url)
    if parsed.netloc in must_download_domains:
        return True

    # blob:// 链接无法使用
    if 'blob:' in url:
        return False

    # 其他情况尝试直接使用
    return False
```

## 批量处理文章中的图片

```python
import re
import subprocess

def process_article_images(markdown_content):
    """
    处理文章中的所有图片，返回可用的 Markdown 内容
    """
    # 匹配 Markdown 图片格式
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

    def replace_image(match):
        alt_text = match.group(1)
        image_url = match.group(2)

        # 跳过本地路径和非 HTTP(S) 链接
        if not image_url.startswith('http'):
            return match.group(0)

        # 调用上传脚本
        result = subprocess.run([
            'python', 'scripts/upload_image.py',
            image_url, alt_text[:20]  # 限制描述长度
        ], capture_output=True, text=True)

        if result.returncode == 0:
            _, new_path, _ = result.stdout.strip().split('|', 2)
            return f'![{alt_text}]({new_path})'
        else:
            # 上传失败，使用占位符
            return f'![{alt_text}](图片上传失败: {image_url})'

    return re.sub(pattern, replace_image, markdown_content)
```

## 完整的图片处理流程实现

```python
import requests
from pathlib import Path
from datetime import datetime
import urllib.parse

def download_image(url, local_path):
    """下载图片到本地"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    # 确保目录存在
    local_path.parent.mkdir(parents=True, exist_ok=True)

    with open(local_path, 'wb') as f:
        f.write(response.content)
    return True

def upload_image_to_siyuan(image_path, config):
    """上传到思源笔记（支持本地和 WebDAV）"""
    # 优先使用本地方式
    if config.get('local_path'):
        # 注意：全局 assets 路径是 {local_path}/data/assets/
        assets_dir = Path(config['local_path']) / 'data' / 'assets'
        assets_dir.mkdir(parents=True, exist_ok=True)

        # 生成唯一文件名
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        ext = Path(image_path).suffix
        target_name = f'img-{timestamp}{ext}'

        # 复制文件到 assets 目录
        import shutil
        shutil.copy2(image_path, assets_dir / target_name)
        return f'assets/{target_name}'

    # 本地方式不可用，尝试 WebDAV
    # ... WebDAV 上传逻辑

    return None

def process_image_url(image_url, description, config):
    """完整的图片处理流程"""
    temp_dir = Path(__file__).parent / 'temp_images'
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. 下载到临时文件
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    ext = Path(urllib.parse.urlparse(image_url).path).suffix or '.jpg'
    temp_path = temp_dir / f'temp_{timestamp}{ext}'

    if not download_image(image_url, temp_path):
        return None

    # 2. 上传到思源
    asset_path = upload_image_to_siyuan(temp_path, config)

    # 3. 删除临时文件（无论成功失败都要清理）
    try:
        temp_path.unlink()
    except:
        pass

    return asset_path
```

## 常见问题

### Q: subprocess 调用时的编码问题

```python
# 错误：没有指定编码处理
result = subprocess.run([...], capture_output=True, text=True)

# 正确：指定 errors='ignore' 避免编码错误
result = subprocess.run([...], capture_output=True, text=True,
                        encoding='utf-8', errors='ignore')
```

### Q: 图片 URL 没有扩展名怎么办？

```python
from urllib.parse import urlparse
from pathlib import Path

ext = Path(urlparse(image_url).path).suffix or '.jpg'
```

### Q: 如何处理 blob:// 链接？

blob:// 链接是浏览器端的临时链接，无法直接访问。需要跳过：

```python
if 'blob:' in image_url:
    return ''  # 移除无效图片引用
```

## 最佳实践

| 项目 | 说明 |
|-----|------|
| **资源目录位置** | 全局 assets 路径：`{local_path}/data/assets/` |
| **图片引用语法** | `assets/filename.ext`（相对于 data 目录） |
| **临时文件位置** | `scripts/temp_images/` 或系统临时目录 |
| **文件命名** | 使用时间戳避免冲突：`img-20260126120000.jpg` |
| **错误处理** | 下载/上传失败时清理临时文件 |
| **并发处理** | 图片处理应串行执行，避免资源冲突 |
| **超时设置** | 下载 30 秒，API 调用 60 秒 |

### 目录结构说明

```
{local_path}/              # 思源工作目录
├── data/                  # 数据目录
│   ├── assets/           # 全局资源目录 ← 图片存放位置
│   │   └── img-xxx.jpg
│   └── {box_id}/         # 笔记本目录
└── conf/                 # 配置目录
```

**配置文件中的 `local_path` 应指向思源工作目录**：
```json
{
  "local_path": "Y:\\note\\siyuan",
  "api_url": "http://127.0.0.1:6806/",
  "api_token": "your_token"
}
```
