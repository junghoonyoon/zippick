"""Deployment must prepare dependencies only for the exact released commit."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/exe-dev/prepare-runtime.sh'


def runtime(tmp_path):
    sha = 'a' * 40
    app = tmp_path / 'app'
    release = app / 'releases' / sha
    release.mkdir(parents=True)
    (app / 'current').symlink_to(release, target_is_directory=True)
    (release / 'requirements-future-transformation.txt').write_text('shapely>=2.1,<3\n')
    commands = tmp_path / 'bin'
    commands.mkdir()
    log = tmp_path / 'calls'
    for name in ('python', 'systemctl', 'curl'):
        executable = commands / name
        executable.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$RUNTIME_TEST_LOG"\n')
        executable.chmod(0o755)
    env = {**os.environ, 'PATH': str(commands) + os.pathsep + os.environ['PATH'],
           'EXE_DEV_APP_ROOT': str(app), 'EXE_DEV_VENV_DIR': str(tmp_path),
           'RUNTIME_TEST_LOG': str(log)}
    return sha, env, log, release


def test_wrong_release_is_rejected_before_installing_or_restarting(tmp_path):
    sha, env, log, _ = runtime(tmp_path)
    result = subprocess.run(['bash', str(SCRIPT), 'b' * 40], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not log.exists()


def test_exact_release_installs_its_dependencies_then_restarts_and_checks_health(tmp_path):
    sha, env, log, release = runtime(tmp_path)
    result = subprocess.run(['bash', str(SCRIPT), sha], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert str(release / 'requirements-future-transformation.txt') in calls[0]
    assert 'pip --disable-pip-version-check install' in calls[0]
    assert 'import shapely, pyproj' in calls[1]
    assert calls[2] == 'systemctl --user restart zippick.service'
    assert calls[3].startswith('curl --fail --silent --output /dev/null http://127.0.0.1:8766/')
