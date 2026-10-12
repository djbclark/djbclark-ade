import json
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


def _start_dir(start_path: PathLike) -> Path:
    path = Path(start_path).resolve()
    return path if path.is_dir() else path.parent


def find_config_file(start_path: PathLike, max_levels: int = 6) -> Optional[Path]:
    current_dir = _start_dir(start_path)

    for _ in range(max_levels):
        for candidate in (
            current_dir / ".claude" / "siyuan.json",
            current_dir / "siyuan.json",
        ):
            if candidate.exists():
                return candidate

        if current_dir == current_dir.parent:
            break
        current_dir = current_dir.parent

    return None


def read_config(start_path: PathLike, max_levels: int = 6) -> dict:
    config_file = find_config_file(start_path, max_levels=max_levels)
    if not config_file:
        raise FileNotFoundError(
            "配置文件未找到。"
            "请确保 .claude/siyuan.json 或 siyuan.json 存在于项目根目录或 skill 目录的上级目录中。"
        )

    with open(config_file, "r", encoding="utf-8") as file:
        return json.load(file)


def resolve_assets_dir(local_path: PathLike) -> Path:
    return Path(local_path) / "data" / "assets"

