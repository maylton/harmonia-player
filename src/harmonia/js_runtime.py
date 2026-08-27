from __future__ import annotations

import json
from abc import ABC, abstractmethod


class JavaScriptRuntimeError(RuntimeError):
    pass


class JavaScriptRuntime(ABC):
    """Minimal synchronous JavaScript engine used by YouTube cipher transforms."""

    MAX_INPUT = 64 * 1024
    MAX_RESULT = 256 * 1024

    @abstractmethod
    def _evaluate(self, code: str) -> str | None:
        raise NotImplementedError

    def execute(self, code: str) -> None:
        self._evaluate(f"{code}\n;undefined;")

    def evaluate_text(self, expression: str, *, max_result: int | None = None) -> str | None:
        limit = self.MAX_RESULT if max_result is None else max(1, min(max_result, self.MAX_RESULT))
        wrapper = (
            "(function(){try{const value=("
            + expression
            + ");if(value==null)return '';const text=String(value);"
            + f"return text.length<={limit}?text:'';"
            + "}catch(e){return '';}})()"
        )
        value = self._evaluate(wrapper)
        return value if value else None

    def call(self, function_name: str, value: str) -> str | None:
        if not function_name.replace("_", "a").replace("$", "a").isalnum():
            raise ValueError("Invalid JavaScript function name")
        if len(value) > self.MAX_INPUT:
            return None
        return self.evaluate_text(f"{function_name}({json.dumps(value)})")


class QtJavaScriptRuntime(JavaScriptRuntime):
    def __init__(self) -> None:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtQml import QJSEngine

        if QCoreApplication.instance() is None:
            raise JavaScriptRuntimeError("QJSEngine requires a QCoreApplication")
        self._engine = QJSEngine()

    def _evaluate(self, code: str) -> str | None:
        result = self._engine.evaluate(code)
        if result.isError():
            line = result.property("lineNumber").toInt()
            message = result.toString()
            raise JavaScriptRuntimeError(f"JavaScript error at line {line}: {message}")
        if result.isUndefined() or result.isNull():
            return None
        return result.toString()


class JavaScriptCoreRuntime(JavaScriptRuntime):
    def __init__(self) -> None:
        import gi

        gi.require_version("JavaScriptCore", "6.0")
        from gi.repository import JavaScriptCore

        self._context = JavaScriptCore.Context.new()

    def _evaluate(self, code: str) -> str | None:
        value = self._context.evaluate(code, -1)
        if value is None:
            return None
        try:
            if value.is_undefined() or value.is_null():
                return None
            return value.to_string()
        except Exception as exc:
            raise JavaScriptRuntimeError(str(exc)) from exc


def create_javascript_runtime() -> JavaScriptRuntime:
    """Choose a JS engine already shipped by the active Harmonia frontend runtime."""
    try:
        return QtJavaScriptRuntime()
    except (ImportError, JavaScriptRuntimeError):
        pass

    try:
        return JavaScriptCoreRuntime()
    except (ImportError, ValueError) as exc:
        raise JavaScriptRuntimeError(
            "Nenhum runtime JavaScript compatível está disponível para resolver o stream."
        ) from exc
