import os
import sys

# Add the src directory to sys.path so that tests can import modules without ModuleNotFoundError
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src'))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
