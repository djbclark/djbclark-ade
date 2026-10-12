#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
思源笔记图片插入脚本

功能：
1. 在指定文档中插入图片
2. 支持本地 assets 路径和 URL 链接两种方式
3. 自动查找文档（通过标题匹配）

使用方法：
    # 插入本地 assets 图片
    python insert_image.py <doc_title> <image_path> [caption]

    # 插入 URL 图片
    python insert_image.py <doc_title> <url> [caption] --url

示例：
    # 本地图片
    python insert_image.py "我的笔记" "assets/diagram.svg" "流程图"

    # URL 图片
    python insert_image.py "我的笔记" "https://example.com/image.png" "网络图片" --url
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


def find_config_file():
    """查找思源笔记配置文件"""
    return shared_find_config_file(__file__)


def read_config():
    """读取思源笔记配置文件"""
    return shared_read_config(__file__)


def find_doc_by_title(config, title):
    """通过标题查找文档"""
    api_url = config.get("api_url", "")
    api_token = config.get("api_token", "")

    if not api_url.endswith("/"):
        api_url += "/"

    headers = {
        "Content-Type": "application/json",
    }
    if api_token:
        headers["Authorization"] = f"Token {api_token}"

    # SQL 查询查找包含指定标题的文档
    stmt = f"SELECT * FROM blocks WHERE content LIKE '%{title}%' AND type = 'd'"

    response = requests.post(
        urljoin(api_url, "api/query/sql"),
        headers=headers,
        json={"stmt": stmt},
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(f"Query failed: {response.text}")

    data = response.json()
    if data.get("code") != 0:
        raise Exception(f"Query failed: {data.get('msg')}")

    blocks = data.get("data", [])
    if not blocks:
        raise Exception(f"Document not found: {title}")

    # 找到最匹配的文档
    for block in blocks:
        content = block.get("content", "")
        if title in content:
            return block.get("id")

    raise Exception(f"Document not found: {title}")


def append_image_to_doc(doc_id, image_path, caption, is_url=False, config=None):
    """在文档末尾追加图片块

    Args:
        doc_id: 文档块 ID
        image_path: 图片路径（本地 assets 路径或 URL）
        caption: 图片说明文字
        is_url: 是否为 URL 链接
        config: 配置对象
    """
    api_url = config.get("api_url", "") if config else ""
    api_token = config.get("api_token", "") if config else ""

    if not api_url.endswith("/"):
        api_url += "/"

    headers = {
        "Content-Type": "application/json",
    }
    if api_token:
        headers["Authorization"] = f"Token {api_token}"

    # 准备图片内容
    if caption:
        image_markdown = f"![{caption}]({image_path} \"{caption}\")"
    else:
        image_markdown = f"![]({image_path})"

    # 添加时间戳注释
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"\n{image_markdown}\n\n*Inserted at {timestamp}*\n"

    response = requests.post(
        urljoin(api_url, "api/block/appendBlock"),
        headers=headers,
        json={
            "dataType": "markdown",
            "data": content,
            "parentID": doc_id,
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(f"Append block failed: {response.text}")

    result = response.json()
    if result.get("code") != 0:
        raise Exception(f"Append block failed: {result.get('msg')}")

    return result.get("data")


def print_usage():
    """打印使用说明"""
    print("思源笔记图片插入脚本")
    print("=" * 50)
    print()
    print("使用方法:")
    print(f"  {sys.argv[0]} <doc_title> <image_path> [caption] [--url]")
    print()
    print("参数:")
    print("  doc_title   - 目标文档标题（支持部分匹配）")
    print("  image_path  - 图片路径")
    print("                 本地: assets/image.svg")
    print("                 URL:  https://example.com/image.png")
    print("  caption     - 图片说明文字（可选）")
    print("  --url       - 标识 image_path 为 URL（可选）")
    print()
    print("示例:")
    print(f"  {sys.argv[0]} \"我的笔记\" \"assets/diagram.svg\" \"流程图\"")
    print(f"  {sys.argv[0]} \"我的笔记\" \"https://example.com/image.png\" \"网络图片\" --url")
    print()
    print("返回格式:")
    print("  成功: SUCCESS|块ID|消息")
    print("  失败: ERROR|错误消息")
    print()


def main():
    """主函数"""
    if len(sys.argv) < 3:
        print_usage()
        sys.exit(1)

    # 解析参数
    doc_title = sys.argv[1]
    image_path = sys.argv[2]
    caption = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3] == "--url" else ""
    is_url = "--url" in sys.argv

    # 如果 --url 在 caption 位置
    if len(sys.argv) > 3 and sys.argv[3] == "--url":
        caption = sys.argv[4] if len(sys.argv) > 4 else ""

    try:
        # 读取配置
        config = read_config()

        # 查找文档
        doc_id = find_doc_by_title(config, doc_title)

        # 插入图片
        block_id = append_image_to_doc(doc_id, image_path, caption, is_url, config)

        # 输出成功结果
        print(f"SUCCESS|{block_id}|Image inserted successfully")

    except Exception as e:
        # 输出错误信息
        print(f"ERROR|{str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
