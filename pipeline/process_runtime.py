"""Launch system tools without forking a loaded macOS geospatial runtime."""
import shutil
import subprocess
import sys


def run(command, **kwargs):
    if sys.platform == "darwin":
        executable = kwargs.get("executable") or shutil.which(command[0])
        if not executable:
            raise FileNotFoundError(command[0])
        # CPython uses posix_spawn on macOS only with an absolute executable and
        # close_fds=False. Python descriptors are non-inheritable by default.
        # A fork would run GDAL/PROJ's child cleanup handlers and can segfault
        # before ssh/curl even starts, producing a macOS Python crash dialog.
        kwargs["executable"] = executable
        kwargs["close_fds"] = False
    return subprocess.run(command, **kwargs)
