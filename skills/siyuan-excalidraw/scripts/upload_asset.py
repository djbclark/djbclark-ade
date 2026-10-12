#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
思源笔记 Excalidraw SVG 资源上传脚本

功能：
1. 读取 siyuan.json 配置文件
2. 根据 local_path 和 remote_path 决定保存方式
3. 支持本地保存和 WebDAV 上传
4. 返回思源笔记可用的资源路径

使用方法：
    python upload_asset.py <svg_content> <topic>

示例：
    python upload_asset.py "<?xml...>" "系统架构"
"""

import json
import os
import sys
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _shared.siyuan_common import find_config_file as shared_find_config_file
from _shared.siyuan_common import read_config as shared_read_config
from _shared.siyuan_common import resolve_assets_dir


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

    Raises:
        FileNotFoundError: 配置文件不存在
        json.JSONDecodeError: 配置文件格式错误
    """
    return shared_read_config(__file__)


def generate_filename(topic):
    """
    生成文件名

    Args:
        topic: 图表主题

    Returns:
        str: SVG 文件名，格式：excalidraw-[主题]-[时间戳].svg
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    # 清理主题名称中的非法字符
    safe_topic = (
        topic.replace(" ", "-").replace("/", "-").replace("\\", "-").replace(":", "-")
    )
    return f"excalidraw-{safe_topic}-{timestamp}.svg"


def save_local(svg_content, local_path, filename):
    """
    保存 SVG 文件到本地

    Args:
        svg_content: SVG 内容
        local_path: 本地路径
        filename: 文件名

    Returns:
        str: 资源路径（相对于 assets 目录）

    Raises:
        OSError: 目录创建或文件写入失败
    """
    # 确保存在 assets 子目录
    assets_path = resolve_assets_dir(local_path)
    assets_path.mkdir(parents=True, exist_ok=True)

    # 保存文件
    file_path = assets_path / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    # 返回相对于 assets 目录的路径
    return f"assets/{filename}"


def upload_webdav(svg_content, remote_config, filename):
    """
    通过 WebDAV 上传 SVG 文件

    Args:
        svg_content: SVG 内容
        remote_config: WebDAV 配置（包含 url, username, password, assets_path）
        filename: 文件名

    Returns:
        str: 资源路径（相对于 assets 目录）

    Raises:
        Exception: WebDAV 上传失败
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
    # 确保 webdav_url 以 / 结尾
    if not webdav_url.endswith("/"):
        webdav_url += "/"

    # 确保 assets_path 不以 / 开头，但以 / 结尾
    assets_path = assets_path.lstrip("/")
    if not assets_path.endswith("/"):
        assets_path += "/"

    upload_url = urljoin(webdav_url, assets_path + filename)

    try:
        # 准备认证
        auth = (username, password)

        # 上传文件
        response = requests.put(
            upload_url,
            data=svg_content.encode("utf-8"),
            auth=auth,
            headers={"Content-Type": "image/svg+xml"},
            timeout=30,
        )

        # 检查响应状态
        if response.status_code in [200, 201, 204]:
            # 返回资源路径（思源笔记中的路径）
            return f"assets/{filename}"
        else:
            raise Exception(
                f"WebDAV 上传失败，状态码: {response.status_code}, 响应: {response.text}"
            )

    except requests.exceptions.RequestException as e:
        raise Exception(f"WebDAV 请求失败: {str(e)}")


def upload_asset(svg_content, topic):
    """
    上传 SVG 资源（自动选择本地保存或 WebDAV 上传）

    Args:
        svg_content: SVG 内容
        topic: 图表主题

    Returns:
        tuple: (成功状态: bool, 资源路径: str, 消息: str)
    """
    try:
        # 读取配置
        config = read_config()

        # 生成文件名
        filename = generate_filename(topic)

        # 获取本地路径
        local_path = config.get("local_path", "")

        # 如果本地路径存在且非空，优先使用本地保存
        if local_path and local_path.strip():
            asset_path = save_local(svg_content, local_path, filename)
            return (
                True,
                asset_path,
                f"已保存到本地: {Path(local_path) / 'data' / 'assets' / filename}",
            )

        # 否则使用 WebDAV 上传
        remote_config = config.get("remote_path", {})

        if remote_config.get("webdav"):
            asset_path = upload_webdav(svg_content, remote_config, filename)
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
    print("思源笔记 Excalidraw SVG 资源上传脚本")
    print("=" * 50)
    print()
    print("使用方法:")
    print(f"  {sys.argv[0]} <svg_content> <topic>")
    print()
    print("参数:")
    print("  svg_content   - SVG 内容（用引号包裹）")
    print("  topic         - 图表主题")
    print()
    print("示例:")
    print(f'  {sys.argv[0]} "<?xml version=\\"1.0\\"...?>" "系统架构"')
    print()
    print("返回格式:")
    print("  成功: ASSET_PATH|消息")
    print("  失败: ERROR|错误消息")
    print()
    print("环境要求:")
    print("  - Python 3.6+")
    print("  - requests 库 (pip install requests)")
    print("  - .claude/siyuan.json 或 siyuan.json 配置文件")
    print()


def main():
    """主函数"""
    if len(sys.argv) < 3:
        print_usage()
        sys.exit(1)

    svg_content = sys.argv[1]
    topic = sys.argv[2]

    # 执行上传
    success, asset_path, message = upload_asset(svg_content, topic)

    if success:
        # 输出资源路径（供其他程序解析）
        print(f"ASSET_PATH|{asset_path}|{message}")
        sys.exit(0)
    else:
        # 输出错误信息
        print(f"ERROR|{message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
