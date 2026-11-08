"""Create a private environment once; subsequent launches do not contact package servers."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
STAMP = ENV / '.papertrail-dependencies'

def main():
    if sys.version_info < (3, 10):
        raise RuntimeError('Please install Python 3.12, then run Papertrail again.')
    fingerprint = hashlib.sha256((ROOT / 'requirements.txt').read_bytes()).hexdigest()
    if not PYTHON.exists():
        print('Preparing Papertrail. First setup requires internet and several minutes.', flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
    if not STAMP.exists() or STAMP.read_text() != fingerprint:
        print('Installing local search and OCR componentsâ€¦', flush=True)
        command = [str(PYTHON), '-m', 'pip', 'install', 'torch==2.15.0']
        if sys.platform != 'darwin':
            command += ['--index-url', 'https://download.pytorch.org/whl/cpu']
        subprocess.run(command, check=True, cwd=ROOT)
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True, cwd=ROOT)
        STAMP.write_text(fingerprint)
    if '--prepare-only' not in sys.argv:
        subprocess.run([str(PYTHON), 'launch.py'], check=True, cwd=ROOT)

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print('Papertrail could not start:', error, file=sys.stderr)
        sys.exit(1)
