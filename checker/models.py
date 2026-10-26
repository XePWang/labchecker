"""
checker.models
判题系统核心数据模型
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Student:
    """点名册中的学生实体"""
    seq: int
    student_id: str
    name: str
    gender: str = ""
    college: str = ""
    major: str = ""
    class_id: str = ""
    phone: Optional[str] = None


@dataclass
class SubmissionFile:
    """提取或解压后的文件记录"""
    path: Path
    original_name: str
    file_type: str  # c_source, cpp_source, image, archive, document, other
    matched_problem: Optional[str] = None  # 1-2, 1-3, 2-1, 2-2, 2-3, 2-4, warmup
    is_warmup: bool = False


@dataclass
class CompileResult:
    """单题编译结果"""
    success: bool
    command: List[str] = field(default_factory=list)
    binary_path: Optional[Path] = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    compat_applied: bool = False
    compat_reasons: List[str] = field(default_factory=list)


@dataclass
class TestCaseResult:
    """单个测试用例评测详情"""
    case_id: str
    input_data: str
    expected_output: str
    actual_output: str
    passed: bool
    score: float
    max_score: float
    timed_out: bool = False
    exit_code: int = 0
    error_message: str = ""
    needs_review: bool = False
    review_reason: str = ""


@dataclass
class ProblemResult:
    """单个题目最终评测结果"""
    problem_id: str
    score: float
    max_score: float
    sub_scores: Dict[str, float] = field(default_factory=dict)
    status: str = "pending"  # passed, partial, failed, compile_error, missing, needs_review
    compile_result: Optional[CompileResult] = None
    test_results: List[TestCaseResult] = field(default_factory=list)
    ai_review: Optional[Dict[str, Any]] = None
    source_files: List[Path] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    needs_review: bool = False
    review_reasons: List[str] = field(default_factory=list)
    is_pending: bool = False


@dataclass
class StudentGrade:
    """学生整场实验评分汇总"""
    student: Student
    total_score: float = 0.0
    max_score: float = 5.0
    status: str = "missing"  # graded, missing, compile_error, needs_review
    problem_results: Dict[str, ProblemResult] = field(default_factory=dict)
    comment: str = ""
    needs_review: bool = False
    review_reasons: List[str] = field(default_factory=list)
    is_pending: bool = False
    optional_results: Dict[str, ProblemResult] = field(default_factory=dict)
