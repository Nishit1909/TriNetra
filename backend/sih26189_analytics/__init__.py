"""Compatibility alias for analytics models serialized under the legacy package name."""

import importlib
import sys


_current_package = importlib.import_module("app.analytics")
_legacy_prefix = __name__
_current_prefix = "app.analytics"

for module_name, module in list(sys.modules.items()):
    if module_name == _current_prefix or module_name.startswith(f"{_current_prefix}."):
        legacy_name = _legacy_prefix + module_name[len(_current_prefix):]
        sys.modules[legacy_name] = module

sys.modules[__name__] = _current_package
