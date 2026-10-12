#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信文章导入思源笔记脚本

用法:
    python import_article.py <文章URL> [笔记本名称]

示例:
    python import_article.py "https://mp.weixin.qq.com/s/xxx" "微信文章收藏"
"""

import requests
import json
import sys
from pathlib import Path
from datetime import datetime

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _shared.siyuan_common import read_config as shared_read_config


class SiYuanImporter:
    """思源笔记导入器"""

    def __init__(self, config_path=None):
        """初始化导入器

        Args:
            config_path: 配置文件路径，默认自动查找 siyuan.json
        """
        self.config = self._load_config(config_path)
        if not self.config:
            raise Exception("配置文件未找到")

    def _load_config(self, config_path=None):
        """加载配置文件"""
        if config_path:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        return shared_read_config(config_path or __file__)

    def _request(self, endpoint, data=None):
        """发送 API 请求

        Args:
            endpoint: API 端点（如 /api/notebook/createNotebook）
            data: 请求数据（字典）

        Returns:
            API 响应的 data 字段，失败返回 None
        """
        url = f"{self.config['api_url'].rstrip('/')}{endpoint}?token={self.config['api_token']}"

        try:
            response = requests.post(
                url,
                json=data,
                headers={'Content-Type': 'application/json'}
            )
            result = response.json()

            if result.get('code') == 0:
                return result.get('data')
            else:
                print(f"ERROR|{result.get('msg', '请求失败')}|")
                return None
        except Exception as e:
            print(f"ERROR|{str(e)}|")
            return None

    def create_notebook(self, name):
        """创建笔记本

        Args:
            name: 笔记本名称

        Returns:
            笔记本 ID，失败返回 None
        """
        data = self._request('/api/notebook/createNotebook', {'name': name, 'icon': ''})
        if data:
            return data['notebook']['id']
        return None

    def ensure_notebook_exists(self, name):
        """确保笔记本存在，不存在则创建

        Args:
            name: 笔记本名称

        Returns:
            笔记本 ID
        """
        # 先查询是否已存在
        notebooks = self._request('/api/notebook/lsNotebooks')
        if notebooks:
            for nb in notebooks:
                if nb.get('name') == name:
                    return nb.get('id')

        # 不存在则创建
        return self.create_notebook(name)

    def create_document(self, notebook_id, title, content):
        """创建文档

        Args:
            notebook_id: 笔记本 ID
            title: 文档标题
            content: Markdown 格式的内容

        Returns:
            文档 ID，失败返回 None
        """
        # 清理标题，移除特殊字符
        safe_title = title.replace('/', '-').replace('\\', '-').replace(':', '-')
        # 限制标题长度
        if len(safe_title) > 50:
            safe_title = safe_title[:50]

        path = f'/{safe_title}'

        data = self._request('/api/filetree/createDocWithMd', {
            'notebook': notebook_id,
            'path': path,
            'markdown': content
        })

        if data:
            return data
        return None

    def verify_document(self, doc_id):
        """验证文档是否创建成功

        Args:
            doc_id: 文档 ID

        Returns:
            内容块数量，失败返回 -1
        """
        query = f"SELECT COUNT(*) as count FROM blocks WHERE root_id='{doc_id}'"
        response = requests.post(
            f"{self.config['api_url']}/api/query/sql?token={self.config['api_token']}",
            json={'stmt': query},
            headers={'Content-Type': 'application/json'}
        )

        result = response.json()
        if result.get('code') == 0 and result.get('data'):
            return result['data'][0]['count']
        return -1


def format_article_content(title, content, url, author='', cover_image=''):
    """格式化文章内容为标准 Markdown 格式

    Args:
        title: 文章标题
        content: 文章正文内容
        url: 文章链接
        author: 作者（可选）
        cover_image: 封面图片 URL（可选）

    Returns:
        格式化后的 Markdown 内容
    """
    # 构建元信息块
    metadata = []
    if author:
        metadata.append(f"**作者**：{author}")
    metadata.append(f"**来源**：微信公众号")
    metadata.append(f"**原始链接**：{url}")
    metadata.append(f"**导入时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    markdown = f"# {title}\n\n"

    # 添加封面图（如果有）
    if cover_image and cover_image.startswith('http'):
        markdown += f"![封面图]({cover_image})\n\n"

    # 添加元信息
    markdown += "---\n\n" + "\n".join(metadata) + "\n\n---\n\n"

    # 添加正文内容
    markdown += content

    return markdown


def import_wechat_article(url, notebook_name='知识储备', title='', content='', author='', cover_image=''):
    """导入微信文章到思源笔记

    Args:
        url: 文章 URL
        notebook_name: 目标笔记本名称
        title: 文章标题
        content: 文章内容（Markdown 格式）
        author: 作者
        cover_image: 封面图 URL

    Returns:
        (success, message, doc_id)
    """
    try:
        importer = SiYuanImporter()

        # 确保笔记本存在
        notebook_id = importer.ensure_notebook_exists(notebook_name)
        if not notebook_id:
            return (False, "创建笔记本失败", None)

        # 格式化文章内容
        markdown = format_article_content(
            title=title or "未命名文章",
            content=content,
            url=url,
            author=author,
            cover_image=cover_image
        )

        # 创建文档
        doc_id = importer.create_document(notebook_id, title or "未命名文章", markdown)
        if not doc_id:
            return (False, "创建文档失败", None)

        # 验证文档
        block_count = importer.verify_document(doc_id)
        if block_count > 0:
            return (True, f"文档创建成功，共 {block_count} 个内容块", doc_id)
        else:
            return (False, "文档验证失败", doc_id)

    except Exception as e:
        return (False, f"导入失败: {str(e)}", None)


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python import_article.py <文章URL> [笔记本名称]")
        sys.exit(1)

    url = sys.argv[1]
    notebook_name = sys.argv[2] if len(sys.argv) > 2 else "知识储备"

    # 注意：实际使用时，需要先使用 web-reader 工具获取文章内容
    # 这里只是示例框架
    print(f"ERROR|需要先使用 web-reader 获取文章内容|")
    print(f"INFO|URL: {url}|")
    print(f"INFO|目标笔记本: {notebook_name}|")


if __name__ == '__main__':
    main()
