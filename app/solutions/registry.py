"""方案注册表：名称 → 工厂函数。

注册表不依赖 config 模块（仅类型注解层面引用），保持 core → 顶层的依赖方向；
注册时机由 register_all() 显式控制，避免 import 副作用成为正确性的一部分。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from app.solutions.base import Solution

if TYPE_CHECKING:
    from app.config import Settings

_factories: dict[str, Callable[[Settings], Solution]] = {}


def register(name: str, factory: Callable[[Settings], Solution]) -> None:
    if name in _factories:
        raise ValueError(f"solution '{name}' already registered")
    _factories[name] = factory


def get_solution(name: str, settings: Settings) -> Solution:
    if name not in _factories:
        raise KeyError(name)
    return _factories[name](settings)


def list_solutions() -> list[str]:
    return sorted(_factories)
