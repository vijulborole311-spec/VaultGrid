"""Start 3 DataNodes + Cloud Controller on this laptop and open the dashboard. Press Ctrl+C to stop."""
import subprocess, sys, time, webbrowser
procs = [subprocess.Popen([sys.executable, "datanode.py", str(p)]) for p in (6001, 6002, 6003)]
procs.append(subprocess.Popen([sys.executable, "namenode.py"]))
time.sleep(3)
webbrowser.open("http://127.0.0.1:5000")
print("\nDashboard: http://127.0.0.1:5000   (Ctrl+C to stop everything)")
try:
    while True: time.sleep(1)
except KeyboardInterrupt:
    for p in procs: p.terminate()
