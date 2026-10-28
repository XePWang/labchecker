"""
checker.labs.base
实验评测基类与接口契约
"""
from abc import ABC, abstractmethod
from copy import deepcopy

from checker.scoring import finalize_grade, finalize_problem, select_candidate, candidate_record
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from checker.models import CompileResult, CompileTask, ProblemResult, Student, StudentGrade, SubmissionFile


class BaseLabJudge(ABC):
    """所有实验判题器的抽象基类"""

    def __init__(self, lab_id: str, max_score: float = 5.0):
        self.lab_id = lab_id.lower()
        self.max_score = max_score

    @abstractmethod
    def collect_compile_tasks(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
    ) -> List[CompileTask]:
        """收集单个学生所有题目的源码编译任务"""
        pass

    def grade_candidates(self, problem_id, evaluate, arguments):
        sources = arguments['sources']
        if not sources:
            return finalize_problem(evaluate(**arguments))
        evaluated = []
        for index, source in enumerate(sources):
            single = dict(arguments)
            single['sources'] = [source]
            single['build_dir'] = arguments['build_dir'] / f'{problem_id}_candidate_{index}'
            compiled = arguments.get('precompiled')
            if compiled is not None:
                key = (arguments['student'].student_id, problem_id, index)
                single['precompiled'] = {(key[0], key[1], 0): compiled[key]} if key in compiled else {}
            result = finalize_problem(evaluate(**single))
            evaluated.append(dict(index=index, source=source, result=result))
        chosen, pending = select_candidate(evaluated)
        result = deepcopy(chosen['result'])
        result.source_files = list(sources)
        result.candidate_evaluations = [candidate_record(c['index'],c['source'],c['result']) for c in evaluated]
        result.chosen_candidate = candidate_record(chosen['index'],chosen['source'],chosen['result'])
        result.chosen_candidate['reason'] = f"完整评定后最高分版本 ({result.score:.2f}/{result.max_score:.2f})"
        if pending:
            result.is_pending = result.needs_review = True
            result.status = 'needs_review'
            result.review_reasons.append('存在尚未完成评定的候选版本，最高分结论待复核')
            result.chosen_candidate['reason']='当前已确认最佳版本；尚有未定候选，最终最高分待复核'
            # With a single unresolved version, unrelated confirmed penalties
            # remain confirmed. Across competing versions they are not final.
            if not chosen['result'].is_pending or len(evaluated)>1:
                for item in result.check_items:
                    if item.deduction:
                        item.deduction = None
                        item.needs_review = True
                        item.completion_status = '待复核'
                        item.deduction_reason = '最高分候选尚未确定，该项最终扣分待复核'
        if len(sources)>1:
            result.notes.append(f"检测到 {len(sources)} 份源码候选，完整评定后择优采用最高分版本: {chosen['source'].name}")
        return result

    def grade_student(self, student, files, build_dir, mock_ai=False, precompiled=None):
        grade = self._grade_student(student, files, build_dir, mock_ai, precompiled)
        finalize_grade(grade)
        grade.comment = self.generate_comment(grade)
        return grade

    @abstractmethod
    def _grade_student(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
        mock_ai: bool = False,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
    ) -> StudentGrade:
        """对单个学生评测本实验所有题目并返回成绩单"""
        pass

    @abstractmethod
    def generate_comment(self, grade: StudentGrade) -> str:
        """根据学生代码、编译与测试执行事实，动态生成不少于50字的实验评语"""
        pass
