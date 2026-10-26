"""
checker.labs.base
实验评测基类与接口契约
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from checker.models import ProblemResult, Student, StudentGrade, SubmissionFile


class BaseLabJudge(ABC):
    """所有实验判题器的抽象基类"""

    def __init__(self, lab_id: str, max_score: float = 5.0):
        self.lab_id = lab_id.lower()
        self.max_score = max_score

    @abstractmethod
    def grade_student(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
        mock_ai: bool = False,
    ) -> StudentGrade:
        """对单个学生评测本实验所有题目并返回成绩单"""
        pass

    @abstractmethod
    def generate_comment(self, grade: StudentGrade) -> str:
        """根据学生代码、编译与测试执行事实，动态生成不少于50字的实验评语"""
        pass
