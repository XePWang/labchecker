"""Shared scoring: exact weights, cent allocation, finalization and candidate ordering."""
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from functools import wraps
from inspect import signature
from typing import Dict, List

from checker.models import ProblemResult, StudentGrade

class ScoringConsistencyError(ValueError):
    """Scores and their evidence disagree; do not publish contradictory reports."""

def cents(value) -> int:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ScoringConsistencyError('评分必须是有限数值')
    return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def money(value) -> float:
    return cents(value) / 100

def allocate(total_cents: int, weights) -> List[int]:
    """Largest remainder, stable input-order tie break; never creates a cent."""
    weights = [Fraction(str(w)) for w in weights]
    if total_cents < 0 or any(w < 0 for w in weights):
        raise ScoringConsistencyError('分值与权重不得为负')
    if not weights:
        if total_cents:
            raise ScoringConsistencyError('无评分项可分配分值')
        return []
    denominator = sum(weights)
    if not denominator:
        if total_cents:
            raise ScoringConsistencyError('零权重无法吸收扣分')
        return [0] * len(weights)
    exact = [w * total_cents / denominator for w in weights]
    result = [x.numerator // x.denominator for x in exact]
    order = sorted(range(len(result)), key=lambda i: (-(exact[i]-result[i]), i))
    for i in order[:total_cents-sum(result)]:
        result[i] += 1
    return result

def rounded_fraction(value: Fraction) -> int:
    # non-negative rational amount in cents, exact ROUND_HALF_UP
    return (2*value.numerator+value.denominator)//(2*value.denominator)

def apply_case_plan(problem: ProblemResult) -> None:
    cases = problem.test_results
    if problem.case_budget is None or not cases:
        return
    budget = cents(problem.case_budget)
    if not 0<=budget<=cents(problem.max_score):
        raise ScoringConsistencyError(f'{problem.problem_id}: 用例预算超出题目预算')
    groups = problem.case_groups
    indices = [i for group in groups.values() for i in group]
    if sorted(indices) != list(range(len(cases))):
        raise ScoringConsistencyError(f'{problem.problem_id}: 用例必须恰好归入一个计分分项')
    by_name = {item.sub_item:item for item in problem.check_items}
    if any(name not in by_name for name in groups):
        raise ScoringConsistencyError(f'{problem.problem_id}: 缺少用例分项')
    passed = [i for i,c in enumerate(cases) if c.passed]
    failed = [i for i,c in enumerate(cases) if not c.passed]
    earned = rounded_fraction(Fraction(budget*len(passed),len(cases)))
    # Allocate displayed cents within pass/fail partitions so case totals, bounds,
    # group deductions and the exact equal-weight aggregate all agree.
    for ids,total in [(passed,earned),(failed,budget-earned)]:
        for i,amount in zip(ids,allocate(total,[1]*len(ids))):
            cases[i].max_score = amount/100
            cases[i].score = amount/100 if cases[i].passed else 0.0
    known_failed = {i for i in failed if not cases[i].needs_review}
    pending = any(c.needs_review for c in cases)
    counts = [sum(i in known_failed for i in ids) for ids in groups.values()]
    deduction_total = (rounded_fraction(Fraction(budget*sum(counts),len(cases)))
                       if pending else budget-earned)
    deductions = allocate(deduction_total,counts)
    for (name,ids),ded in zip(groups.items(),deductions):
        item = by_name[name]
        if item.deduction is None or any(cases[i].needs_review for i in ids):
            item.deduction = None
            item.needs_review = True
            item.completion_status = '待复核'
        else:
            item.deduction = ded/100
            # Keep the factual reason and show the finalized allocation, rather
            # than stale category-weight amounts embedded by individual judges.
            failed_count = sum(not cases[i].passed for i in ids)
            item.deduction_reason = (f'{failed_count}/{len(ids)}项未通过，按全部{len(cases)}例均分预算{budget/100:.2f}，本项扣{ded/100:.2f}分（含舍入分配）' if failed_count else '')
    if problem.case_component:
        problem.sub_scores[problem.case_component] = earned/100

def finalize_problem(problem: ProblemResult) -> ProblemResult:
    problem.max_score = money(problem.max_score)
    problem.score = money(problem.score)
    if problem.score < 0 or problem.score > problem.max_score:
        raise ScoringConsistencyError(f'{problem.problem_id}: 得分越界')
    apply_case_plan(problem)
    unknown = any(i.deduction is None for i in problem.check_items)
    problem.is_pending = bool(problem.is_pending or unknown)
    problem.needs_review = bool(problem.needs_review or problem.is_pending or any(i.needs_review for i in problem.check_items))
    if problem.is_pending:
        problem.status = 'needs_review'
        return problem
    if not problem.check_items:
        if problem.max_score:
            raise ScoringConsistencyError(f'{problem.problem_id}: 缺少扣分证据')
        return problem
    values = [cents(i.deduction) for i in problem.check_items]
    if any(d<0 for d in values) or sum(values)>cents(problem.max_score):
        raise ScoringConsistencyError(f'{problem.problem_id}: 扣分预算越界')
    if problem.case_budget is not None and problem.test_results:
        # This is the only source for the final score: shared equal-weight cases
        # plus the lab's explicit non-case penalties (handwriting, format, etc.).
        problem.score = (cents(problem.max_score)-sum(values))/100
    else:
        required = cents(problem.max_score)-cents(problem.score)
        delta = required-sum(values)
        if abs(delta)>1:
            raise ScoringConsistencyError(f'{problem.problem_id}: 扣分{sum(values)/100:.2f}与应扣{required/100:.2f}不一致')
        if delta:
            eligible=[i for i,d in enumerate(values) if d>0]
            if not eligible:
                raise ScoringConsistencyError(f'{problem.problem_id}: 无明确扣分项可吸收尾差')
            values[eligible[-1]] += delta
    for item,amount in zip(problem.check_items,values):
        item.deduction=amount/100
    if cents(sum(i.deduction for i in problem.check_items)) != cents(problem.max_score)-cents(problem.score):
        raise ScoringConsistencyError(f'{problem.problem_id}: 扣分未闭合')
    if problem.max_score and problem.status not in {'compile_error','missing','missing_source'}:
        problem.status = 'passed' if problem.score==problem.max_score else 'partial' if problem.score else 'failed'
    return problem

def finalize_grade(grade: StudentGrade) -> StudentGrade:
    for problem in [*grade.problem_results.values(),*grade.optional_results.values()]:
        finalize_problem(problem)
    problems=list(grade.problem_results.values())
    if problems:
        if cents(sum(p.max_score for p in problems))!=cents(grade.max_score):
            raise ScoringConsistencyError('必做题预算合计与实验满分不符')
        grade.is_pending = grade.is_pending or any(p.is_pending for p in problems)
        grade.total_score = 0.0 if grade.is_pending else sum(cents(p.score) for p in problems)/100
        grade.needs_review = grade.needs_review or any(p.needs_review for p in problems)
        grade.review_reasons=list(dict.fromkeys(grade.review_reasons+[r for p in problems for r in p.review_reasons]))
    grade.max_score=money(grade.max_score)
    grade.total_score=money(grade.total_score)
    if not 0<=grade.total_score<=grade.max_score:
        raise ScoringConsistencyError('实验总分越界')
    if grade.is_pending:
        grade.needs_review=True
        grade.status=grade.status if grade.status in {'ambiguous','conflict'} else 'needs_review'
    elif grade.needs_review and grade.status not in {'missing_source','ambiguous','conflict'}:
        grade.status=grade.status if grade.status in {'ambiguous','conflict'} else 'needs_review'
    return grade

def validate_grade(grade):
    """Publishing must not silently change the already-finalized financial facts."""
    from copy import deepcopy
    def amounts(g):
        return (cents(g.total_score),cents(g.max_score),{
            pid:(cents(p.score),cents(p.max_score),
                 [None if i.deduction is None else cents(i.deduction) for i in p.check_items],
                 [(cents(c.score),cents(c.max_score)) for c in p.test_results])
            for pid,p in {**g.problem_results,**g.optional_results}.items()})
    copy=deepcopy(grade)
    finalize_grade(copy)
    if amounts(copy)!=amounts(grade):
        raise ScoringConsistencyError('评分尚未完成公共最终化，或评分状态中的得分/扣分/用例金额互相矛盾')
    return finalize_grade(grade)

def select_candidate(candidates):
    """Choose one finalized candidate; no case-wise cross-version merge."""
    def key(candidate):
        p=candidate['result']
        optional_quality=sum(c.passed for c in p.test_results) if not p.max_score else 0
        rank={'passed':4,'partial':3,'failed':2,'compile_error':1}.get(p.status,0)
        return (-cents(p.score),p.is_pending,-optional_quality,-rank,
                -int(bool(p.compile_result and p.compile_result.success)),str(candidate['source']))
    confirmed=[c for c in candidates if not c['result'].is_pending]
    chosen=min(confirmed or candidates,key=key)
    # Pending alternatives can still improve a non-full result. Preserve them as
    # unresolved rather than publishing either an invented zero or a false winner.
    unresolved=any(c['result'].is_pending for c in candidates)
    return chosen, unresolved and (chosen['result'].is_pending or (chosen['result'].score<chosen['result'].max_score if chosen['result'].max_score else chosen['result'].status!='passed'))

def candidate_record(index,source,p):
    return dict(index=index,src_path=str(source),filename=source.name,score=p.score,
                total_score=p.score,max_score=p.max_score,
                code_score=p.sub_scores.get('code'),handwritten_score=p.sub_scores.get('handwritten'),
                compile_success=bool(p.compile_result and p.compile_result.success),
                passed_cases=sum(c.passed for c in p.test_results),is_pending=p.is_pending,
                needs_review=p.needs_review,notes=list(p.notes),reviews=list(p.review_reasons),
                check_items=[asdict(i) for i in p.check_items],test_results=[asdict(c) for c in p.test_results])

def scored_problem(problem_id):
    """Public problem boundary: labs evaluate a single complete source version."""
    def decorate(evaluate):
        sig=signature(evaluate)
        @wraps(evaluate)
        def grade(self,*args,**kwargs):
            bound=sig.bind(self,*args,**kwargs)
            bound.apply_defaults()
            return self.grade_candidates(problem_id,evaluate,dict(bound.arguments))
        return grade
    return decorate
