import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
proc = subprocess.Popen(
    [sys.executable, 'run.py'],
    stdout=open('server.log', 'w'),
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
)
print(proc.pid)
