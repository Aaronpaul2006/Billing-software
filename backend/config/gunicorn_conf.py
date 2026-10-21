"""Gunicorn in production: `gunicorn -c config/gunicorn_conf.py config.wsgi`.

Workers default to 2 x CPU + 1 (WEB_CONCURRENCY overrides). Request logs come
from the reverse proxy; gunicorn logs only errors, as text on stderr.
"""

import multiprocessing
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
threads = 1
timeout = 60  # PDF previews of large drafts can take a few seconds
graceful_timeout = 30
keepalive = 5
max_requests = 2000  # recycle workers now and then (memory growth)
max_requests_jitter = 200
accesslog = None
errorlog = "-"
forwarded_allow_ips = "*"  # only the proxy can reach the container
