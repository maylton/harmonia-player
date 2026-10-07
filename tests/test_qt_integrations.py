import inspect
import re

import pytest

pytest.importorskip("PySide6")


def test_every_operation_result_has_a_handler_that_no_attribute_shadows():
    from harmonia.qt_integrations import QtIntegrationsController

    init = inspect.getsource(QtIntegrationsController.__init__)
    attributes = set(re.findall(r"self\.(\w+)\s*(?::[^=]+)?=", init))
    for operation, handler in QtIntegrationsController.OPERATION_HANDLERS.items():
        assert callable(getattr(QtIntegrationsController, handler, None)), operation
        assert handler not in attributes, f"{operation}: self.{handler} is set in __init__"
