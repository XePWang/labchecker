"""
checker.labs
实验评测模块注册
"""
from checker.labs.base import BaseLabJudge
from checker.labs.lab1 import Lab1Judge
from checker.labs.lab2 import Lab2Judge

__all__ = ["BaseLabJudge", "Lab1Judge", "Lab2Judge"]
