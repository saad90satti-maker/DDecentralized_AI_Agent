"""Sandbox executor — safely runs untrusted code in an isolated environment."""

import ast
import logging
import sys
import traceback
from io import StringIO
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("SandboxExecutor")

FORBIDDEN_BUILTINS = {
    "exec", "eval", "compile", "__import__", "open",
    "input", "breakpoint", "memoryview", "bytearray",
}

FORBIDDEN_KEYWORDS = {
    "os", "subprocess", "shutil", "socket", "ctypes",
    "multiprocessing", "threading", "signal", "fcntl",
    "mmap", "sys", "inspect",
}

ALLOWED_BUILTINS = {
    "abs", "all", "any", "ascii", "bin", "bool", "chr", "dict",
    "dir", "divmod", "enumerate", "filter", "float", "format",
    "frozenset", "getattr", "hasattr", "hash", "hex", "id",
    "int", "isinstance", "issubclass", "iter", "len", "list",
    "map", "max", "min", "next", "object", "oct", "ord", "pow",
    "print", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "staticmethod", "str", "sum", "super",
    "tuple", "type", "vars", "zip",
}


def ast_scan(code: str) -> Optional[str]:
    """Scan AST for forbidden constructs. Returns error message or None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno})"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_BUILTINS:
                return f"Forbidden built-in: {func.id}"
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id in FORBIDDEN_KEYWORDS:
                    return f"Forbidden module access: {func.value.id}.{func.attr}"
                if isinstance(func.value, ast.Attribute):
                    inner = func.value
                    while isinstance(inner, ast.Attribute):
                        inner = inner.value
                    if isinstance(inner, ast.Name) and inner.id in FORBIDDEN_KEYWORDS:
                        return f"Forbidden module access chain"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base in FORBIDDEN_KEYWORDS:
                    return f"Forbidden import: {alias.name}"
    return None


class SandboxResult:
    def __init__(self, ok: bool, output: str = "", error: str = "",
                 result: Any = None):
        self.ok = ok
        self.output = output
        self.error = error
        self.result = result

    def __repr__(self) -> str:
        if self.ok:
            return f"SandboxResult(ok=True, output={self.output[:100]})"
        return f"SandboxResult(ok=False, error={self.error[:100]})"


def run_in_sandbox(code: str, timeout: float = 5.0,
                   globals_dict: Optional[Dict[str, Any]] = None) -> SandboxResult:
    """Run Python code in a restricted sandbox."""
    scan_error = ast_scan(code)
    if scan_error:
        return SandboxResult(ok=False, error=scan_error)

    safe_globals = {
        "__builtins__": {k: __builtins__[k] for k in ALLOWED_BUILTINS
                         if k in __builtins__},
        "__name__": "__sandbox__",
    }
    if globals_dict:
        for k, v in globals_dict.items():
            if not k.startswith("_"):
                safe_globals[k] = v

    stdout_capture = StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_capture

    try:
        compiled = compile(code, "<sandbox>", "exec")
        restricted = {"__builtins__": safe_globals["__builtins__"]}
        exec(compiled, restricted)
        output = stdout_capture.getvalue()
        return SandboxResult(ok=True, output=output)
    except Exception as e:
        tb = traceback.format_exc()
        return SandboxResult(ok=False, error=str(e), output=tb)
    finally:
        sys.stdout = old_stdout


def validate_code_safety(code: str) -> Tuple[bool, str]:
    """Validate code for safety and syntax. Returns (is_safe, reason)."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    scan_error = ast_scan(code)
    if scan_error:
        return False, scan_error

    return True, ""


def sandbox_test_code(original_code: str, new_code: str,
                      test_globals: Optional[Dict[str, Any]] = None) -> SandboxResult:
    """Run both original and new code, comparing outputs."""
    orig_result = run_in_sandbox(original_code, globals_dict=test_globals)
    new_result = run_in_sandbox(new_code, globals_dict=test_globals)

    if not new_result.ok:
        return SandboxResult(ok=False, error=f"New code failed: {new_result.error}")

    if orig_result.ok and orig_result.output != new_result.output:
        return SandboxResult(
            ok=False,
            error=f"Output mismatch: original={orig_result.output[:200]} vs new={new_result.output[:200]}",
        )

    return SandboxResult(ok=True, output=new_result.output)
