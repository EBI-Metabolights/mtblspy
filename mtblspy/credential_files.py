"""Private JSON files and cross-platform locks used by credential storage."""

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout


class CredentialStorageError(RuntimeError):
    """Credentials could not be read, saved, or deleted."""


def check_private_path(path, *, directory=False):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise CredentialStorageError(
            "Unable to access your sign-in session. Please try again or contact support."
        ) from None
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(info.st_mode) or info.st_nlink > 1 and not directory:
        raise CredentialStorageError(
            "Unable to access your sign-in session. Please contact support."
        )
    if os.name == "posix" and (
        info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise CredentialStorageError(
            "Unable to access your sign-in session. Please contact support."
        )


def private_directory(path):
    path = Path(path).expanduser().absolute()
    if not path.parent.exists():
        private_directory(path.parent)
    try:
        path.mkdir(exist_ok=True, mode=0o700)
    except OSError:
        raise CredentialStorageError(
            "Unable to access your sign-in session. Please try again or contact support."
        ) from None
    check_private_path(path, directory=True)
    return path


def credential_file_path():
    path = (
        Path(
            os.environ.get(
                "MTBLS_CREDENTIAL_FILE", Path.home() / ".mtblspy" / "credentials.json"
            )
        )
        .expanduser()
        .absolute()
    )
    default = Path.home() / ".mtblspy" / "credentials.json"
    if path == default and os.name == "posix":
        # Older mtblspy versions created these application settings as 755/644.
        # Limit automatic repair to our own default directory and config file.
        _secure_legacy_settings(path.parent, directory=True)
        _secure_legacy_settings(path.parent / "config.json")
    return path


def _secure_legacy_settings(path, *, directory=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise CredentialStorageError(
            "Unable to access your sign-in session. Please try again or contact support."
        ) from None
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected_type(info.st_mode)
        or info.st_uid != os.getuid()
        or not directory
        and info.st_nlink > 1
    ):
        # Leave links, foreign-owned paths, and special files untouched.
        check_private_path(path, directory=directory)
        return
    if stat.S_IMODE(info.st_mode) & 0o077:
        try:
            path.chmod(0o700 if directory else 0o600)
        except OSError:
            raise CredentialStorageError(
                "Unable to update your sign-in session. Please contact support."
            ) from None
    check_private_path(path, directory=directory)


def read_private_json(path):
    path = Path(path)
    try:
        check_private_path(path.parent, directory=True)
        check_private_path(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError):
        raise CredentialStorageError(
            "Your sign-in session could not be loaded. Please sign in again."
        ) from None


def write_private_json(path, data):
    path = Path(path)
    private_directory(path.parent)
    check_private_path(path)
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=".mtblspy-", suffix=".tmp", dir=path.parent
        )
    except OSError:
        raise CredentialStorageError(
            "Unable to save your sign-in session. Please try again or contact support."
        ) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except OSError:
        raise CredentialStorageError(
            "Unable to save your sign-in session. Please try again or contact support."
        ) from None
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            raise CredentialStorageError(
                "Unable to finish updating your sign-in session. Please contact support."
            ) from None


@contextmanager
def credential_lock(path):
    path = Path(path)
    private_directory(path.parent)
    check_private_path(path)
    try:
        with FileLock(path, timeout=35, mode=0o600):
            yield
    except Timeout:
        raise CredentialStorageError(
            "Another command is updating this session. Try again shortly."
        ) from None
    except OSError:
        raise CredentialStorageError(
            "Unable to access your sign-in session. Please try again or contact support."
        ) from None
