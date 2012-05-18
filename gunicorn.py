import multiprocessing

bind = "127.0.0.1:8000"
workers = multiprocessing.cpu_count() * 2 + 1
proc_name = 'putcast'
backlog = 2048
debug = False
daemon = True
pidfile ="/tmp/gunicorn.pid"
logfile ="/tmp/gunicorn.log"