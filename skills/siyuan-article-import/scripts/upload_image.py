#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
思源笔记图片上传脚本

功能：
1. 从网络下载图片
2. 根据 siyuan.json 配置保存到本地或上传到 WebDAV
3. 返回思源笔记可用的资源路径

使用方法：
    python upload_image.py <图片URL> [图片描述]

示例：
    python upload_image.py "https://mmbiz.qpic.cn/xxx/0?wx_fmt=jpeg" "封面图"
"""

import json
import os
import sys
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Optional

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _shared.siyuan_common import find_config_file as shared_find_config_file
from _shared.siyuan_common import read_config as shared_read_config
from _shared.siyuan_common import resolve_assets_dir


# 常见图片扩展名映射
IMAGE_EXTENSIONS = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
    'image/bmp': '.bmp',
}


def find_config_file():
    """
    查找思源笔记配置文件

    按以下顺序逐层向上查找：
    1. .claude/siyuan.json
    2. siyuan.json

    Returns:
        Path: 配置文件路径，如果找不到返回 None
    """
    return shared_find_config_file(__file__)


def read_config():
    """
    读取思源笔记配置文件

    Returns:
        dict: 配置内容
    """
    return shared_read_config(__file__)


def get_image_extension(content_type: str, url: str) -> str:
    """
    根据 Content-Type 或 URL 获取文件扩展名

    Args:
        content_type: 图片的 MIME 类型
        url: 图片 URL

    Returns:
        str: 文件扩展名（如 .jpg, .png）
    """
    # 先从 Content-Type 获取
    if content_type in IMAGE_EXTENSIONS:
        return IMAGE_EXTENSIONS[content_type]

    # 从 URL 路径获取扩展名
    parsed_url = urlparse(url)
    path = parsed_url.path.lower()
    for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp']:
        if path.endswith(ext):
            return ext

    # 默认使用 jpg
    return '.jpg'


def generate_filename(description: str, extension: str) -> str:
    """
    生成图片文件名

    Args:
        description: 图片描述（用于命名）
        extension: 文件扩展名

    Returns:
        str: 文件名，格式：图片-[描述]-[时间戳].扩展名
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    # 清理描述中的非法字符
    safe_description = (
        description.replace(" ", "-")
        .replace("/", "-")
        .replace("\\", "-")
        .replace(":", "-")
        .replace("?", "-")
        .replace("!", "-")
    )[:50]  # 限制长度

    # 如果描述为空，使用默认名称
    if not safe_description:
        safe_description = "image"

    return f"img-{safe_description}-{timestamp}{extension}"


def download_image(image_url: str) -> tuple[bytes, str]:
    """
    从网络下载图片

    Args:
        image_url: 图片 URL

    Returns:
        tuple: (图片二进制数据, Content-Type)

    Raises:
        Exception: 下载失败
    """
    try:
        response = requests.get(image_url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")

        content_type = response.headers.get('Content-Type', 'image/jpeg')
        return response.content, content_type

    except requests.exceptions.RequestException as e:
        raise Exception(f"下载失败: {str(e)}")


def save_local(image_content: bytes, local_path: str, filename: str) -> str:
    """
    保存图片到本地

    Args:
        image_content: 图片二进制数据
        local_path: 本地路径
        filename: 文件名

    Returns:
        str: 资源路径（相对于 assets 目录）
    """
    assets_path = resolve_assets_dir(local_path)
    assets_path.mkdir(parents=True, exist_ok=True)

    file_path = assets_path / filename
    with open(file_path, "wb") as f:
        f.write(image_content)

    # 保存后不删除，因为要保留在 assets 目录供思源笔记使用
    return f"assets/{filename}"


def upload_webdav(image_content: bytes, remote_config: dict, filename: str) -> str:
    """
    通过 WebDAV 上传图片

    Args:
        image_content: 图片二进制数据
        remote_config: WebDAV 配置（包含 url, username, password, assets_path）
        filename: 文件名

    Returns:
        str: 资源路径（相对于 assets 目录）
    """
    webdav_url = remote_config.get("url", "")
    username = remote_config.get("username", "")
    password = remote_config.get("password", "")
    assets_path = remote_config.get("assets_path", "")

    if not all([webdav_url, username, password, assets_path]):
        raise ValueError(
            "WebDAV 配置不完整，需要 url、username、password 和 assets_path"
        )

    # 构建 WebDAV 上传 URL
    if not webdav_url.endswith("/"):
        webdav_url += "/"

    assets_path = assets_path.lstrip("/")
    if not assets_path.endswith("/"):
        assets_path += "/"

    upload_url = urljoin(webdav_url, assets_path + filename)

    # 创建临时文件用于上传
    import tempfile
    temp_file = None
    try:
        # 猜测 Content-Type
        ext = Path(filename).suffix.lower()
        content_type = 'image/jpeg'
        for mime, extension in IMAGE_EXTENSIONS.items():
            if extension == ext:
                content_type = mime
                break

        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            temp_file = tf.name
            tf.write(image_content)

        # 上传临时文件
        with open(temp_file, "rb") as f:
            response = requests.put(
                upload_url,
                data=f,
                auth=(username, password),
                headers={"Content-Type": content_type},
                timeout=30,
            )

        if response.status_code not in [200, 201, 204]:
            raise Exception(
                f"WebDAV 上传失败，状态码: {response.status_code}"
            )

        return f"assets/{filename}"

    except requests.exceptions.RequestException as e:
        raise Exception(f"WebDAV 请求失败: {str(e)}")
    finally:
        # 确保删除临时文件
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass  # 忽略删除失败


def upload_image(image_url: str, description: str = "image") -> tuple[bool, str, str]:
    """
    上传图片（自动选择本地保存或 WebDAV 上传）

    Args:
        image_url: 图片 URL
        description: 图片描述（用于生成文件名）

    Returns:
        tuple: (成功状态: bool, 资源路径: str, 消息: str)
    """
    try:
        # 读取配置
        config = read_config()

        # 下载图片
        image_content, content_type = download_image(image_url)

        # 获取扩展名并生成文件名
        extension = get_image_extension(content_type, image_url)
        filename = generate_filename(description, extension)

        # 获取本地路径
        local_path = config.get("local_path", "")

        # 如果本地路径存在且非空，优先使用本地保存
        if local_path and local_path.strip():
            asset_path = save_local(image_content, local_path, filename)
            return (
                True,
                asset_path,
                f"已保存到本地: {Path(local_path) / 'data' / 'assets' / filename}"
            )

        # 否则使用 WebDAV 上传
        remote_config = config.get("remote_path", {})

        if remote_config.get("webdav"):
            asset_path = upload_webdav(image_content, remote_config, filename)
            return True, asset_path, f"已通过 WebDAV 上传: {filename}"
        else:
            return False, None, "配置错误：local_path 为空且 WebDAV 未启用"

    except FileNotFoundError as e:
        return False, None, f"配置文件错误: {str(e)}"
    except json.JSONDecodeError as e:
        return False, None, f"配置文件格式错误: {str(e)}"
    except Exception as e:
        return False, None, f"上传失败: {str(e)}"


def print_usage():
    """打印使用说明"""
    print("思源笔记图片上传脚本")
    print("=" * 50)
    print()
    print("使用方法:")
    print(f"  {sys.argv[0]} <图片URL> [图片描述]")
    print()
    print("参数:")
    print("  图片URL    - 要上传的图片地址（必填）")
    print("  图片描述   - 用于生成文件名（可选，默认: image）")
    print()
    print("示例:")
    print(f'  {sys.argv[0]} "https://mmbiz.qpic.cn/xxx/0?wx_fmt=jpeg" "封面图"')
    print(f'  {sys.argv[0]} "https://example.com/image.png" ""')
    print()
    print("返回格式:")
    print("  成功: ASSET_PATH|资源路径|消息")
    print("  失败: ERROR|错误消息")
    print()
    print("环境要求:")
    print("  - Python 3.6+")
    print("  - requests 库 (pip install requests)")
    print("  - .claude/siyuan.json 或 siyuan.json 配置文件")


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    image_url = sys.argv[1]
    description = sys.argv[2] if len(sys.argv) > 2 else "image"

    # 执行上传
    success, asset_path, message = upload_image(image_url, description)

    if success:
        print(f"ASSET_PATH|{asset_path}|{message}")
        sys.exit(0)
    else:
        print(f"ERROR|{message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
