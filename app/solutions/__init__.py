"""方案包：注册收敛到 register_all()，由应用启动时显式调用一次。

不在 import 时注册——只 import registry 模块不再会得到"恰好为空"的注册表。
"""

from app.config import Settings
from app.solutions.base import Solution
from app.solutions.cascade import CascadeSolution
from app.solutions.echo.session import EchoSolution
from app.solutions.registry import get_solution, list_solutions, register


def register_all() -> None:
    """幂等：重复调用不产生冲突。"""
    if list_solutions():
        return
    register("cascade", lambda settings: CascadeSolution(settings))
    register("echo", lambda settings: EchoSolution(settings))


__all__ = [
    "Solution",
    "get_solution",
    "list_solutions",
    "register",
    "register_all",
]
