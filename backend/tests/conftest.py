"""Shared test environment: isolate every test from the developer's local DB."""
import atexit
import os
import pathlib
import shutil
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="researchmate-tests-"))
_DB = _TMP / "test.db"

# Set before any app module is imported so app.config uses an isolated database.
os.environ["DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["PDF_DIR"] = str(_TMP / "storage" / "pdfs")
os.environ["SECRET_KEY"] = "researchmate-test-secret-key"
os.environ["AUTO_LOGIN"] = "true"
os.environ["FRONTEND_DIST"] = ""


def _cleanup() -> None:
    shutil.rmtree(_TMP, ignore_errors=True)


atexit.register(_cleanup)
