"""Test bootstrap that forces the repository checkout to win over any installed package
with the same top-level module names (for example, a stray site-packages `phase3`).
"""
import os
import sys

# Most route tests predate sign-in and identify callers with X-User-Id only.
# Tests that exercise real authentication set CAPSTONE_AUTH_REQUIRED=true.
os.environ.setdefault("CAPSTONE_AUTH_REQUIRED", "false")
# Never read the developer's .env (it may hold real SMTP or Slack credentials).
os.environ["CAPSTONE_SKIP_DOTENV"] = "1"
# Keep tests hermetic: never generate a dev signing secret inside the checkout.
os.environ.setdefault("PLATFORM_JWT_SECRET", "pytest-only-signing-secret-at-least-32-bytes")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Remove any shadowing module instance before importing project modules.
for name in list(sys.modules):
    if name == "phase3" or name.startswith("phase3."):
        del sys.modules[name]
