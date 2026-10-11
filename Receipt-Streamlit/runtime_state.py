"""Only synchronization and login throttling are shared between sessions."""
from collections import deque
from threading import Lock

OCR_LOCK = Lock()
LOGIN_LOCK = Lock()
FAILURES = deque()
