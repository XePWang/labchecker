"""Lossless report state; JSON contains the same finalized facts as CSV/Markdown/XLSX."""
from dataclasses import asdict
from pathlib import Path
from checker.models import CheckItem, CompileResult, ProblemResult, Student, StudentGrade, TestCaseResult

SCHEMA_VERSION = 1

def grade_to_dict(grade):
    return asdict(grade)

def grade_from_dict(data):
    def problem(raw):
        raw=dict(raw)
        raw['source_files']=[Path(p) for p in raw.get('source_files',[])]
        raw['check_items']=[CheckItem(**i) for i in raw.get('check_items',[])]
        raw['test_results']=[TestCaseResult(**c) for c in raw.get('test_results',[])]
        if raw.get('compile_result'):
            compiled=dict(raw['compile_result'])
            if compiled.get('binary_path'):compiled['binary_path']=Path(compiled['binary_path'])
            raw['compile_result']=CompileResult(**compiled)
        return ProblemResult(**raw)
    data=dict(data)
    data['student']=Student(**data['student'])
    for name in ['problem_results','optional_results']:
        data[name]={pid:problem(p) for pid,p in data.get(name,{}).items()}
    return StudentGrade(**data)
