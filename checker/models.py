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
    file_type: str  # c_source, cpp_source, image, archive, document, corrupt_archive, other
    matched_problem: Optional[str] = None  # 1-2, 1-3, 2-1, 2-2, 2-3, 2-4, warmup
    is_warmup: bool = False
    note: str = ""
    source_encoding: str = "utf-8"
    encoding_converted: bool = False
    encoding_error: str = ""


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
class CompileTask:
    """公共编译任务单元 (学生 × 题号 × 源码候选)"""
    student_id: str
    problem_id: str                          # 如 "1-2", "1-3", "2-1"
    cand_idx: int                            # 源码候选序号，从 0 开始
    binary_name: str                         # 如 "lab1_2_cand_0"
    src_path: Path                           # 源码文件路径
    build_dir: Path                          # 产物输出目录 (如 build/<student_id>)
    extra_sources: Optional[List[Path]] = None
    include_dirs: Optional[List[Path]] = None


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
class CheckItem:
    """各实验题目的具体检查分项结果"""
    problem_id: str             # 如 "1-1", "1-2", "1-3"
    sub_item: str               # 评分项名称
    submission_status: str      # 提交状态: 已提交, 未提交, 无法归属, 不适用
    completion_status: str      # 达成状态: 已达成, 部分达成, 未达成, 无法验证, 待复核, 不适用
    evidence: str               # 检查依据: 引用具体文件、测试输入与输出、编译诊断、图片或验算内容
    deduction: Optional[float] = 0.0  # 建议扣分: 如 0.0, 0.20, None (若待复核或无法确定)
    deduction_reason: str = ""  # 扣分理由
    agent_note: str = ""        # Agent说明附注
    needs_review: bool = False  # 是否需要复核


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
    check_items: List[CheckItem] = field(default_factory=list)


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

    @property
    def all_check_items(self) -> List[CheckItem]:
        items: List[CheckItem] = []
        for pid in sorted(self.problem_results.keys()):
            items.extend(self.problem_results[pid].check_items)
        for pid in sorted(self.optional_results.keys()):
            items.extend(self.optional_results[pid].check_items)
        return items
