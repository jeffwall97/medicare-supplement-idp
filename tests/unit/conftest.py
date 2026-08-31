import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMON_LAYER_PYTHON = os.path.join(REPO_ROOT, "src", "layers", "common")
FUNCTIONS_DIR = os.path.join(REPO_ROOT, "src", "functions")

if COMMON_LAYER_PYTHON not in sys.path:
    sys.path.insert(0, COMMON_LAYER_PYTHON)


def load_handler_module(function_dir_name):
    """Import a Lambda handler's app.py under a unique module name.

    Every function directory uses the filename app.py, so a plain import
    would collide across functions/tests; each gets loaded under
    "<function_dir_name>_app" instead.
    """
    module_name = f"{function_dir_name}_app"
    if module_name in sys.modules:
        return sys.modules[module_name]

    app_path = os.path.join(FUNCTIONS_DIR, function_dir_name, "app.py")
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
