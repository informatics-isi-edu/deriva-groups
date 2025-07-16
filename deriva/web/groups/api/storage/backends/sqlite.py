#
# Copyright 2025 University of Southern California
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import sqlite3
import time
import fnmatch
from typing import Optional, List, Iterable, Union

class SQLiteBackend:
    """
    A simple SQLite-based key-value store with TTL support.
    """
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS deriva_groups (
                key TEXT PRIMARY KEY,
                value BLOB,
                expires_at REAL
            )
        """)
        self.conn.commit()

    def setex(self, key: str, value: Union[str, bytes], ttl: int) -> None:
        expires_at = time.time() + ttl
        blob = value if isinstance(value, (bytes, bytearray)) else value.encode()
        self.conn.execute("""
            INSERT OR REPLACE INTO deriva_groups (key, value, expires_at)
            VALUES (?, ?, ?)
        """, (key, blob, expires_at))
        self.conn.commit()

    def get(self, key: str) -> Optional[bytes]:
        cur = self.conn.execute("""
            SELECT value, expires_at FROM deriva_groups WHERE key = ?
        """, (key,))
        row = cur.fetchone()
        if not row:
            return None
        value, expires_at = row
        if expires_at is not None and time.time() >= expires_at:
            # expired
            self.delete(key)
            return None
        return value

    def delete(self, key: str) -> None:
        self.conn.execute("DELETE FROM deriva_groups WHERE key = ?", (key,))
        self.conn.commit()

    def keys(self, pattern: str) -> List[str]:
        # Simple in-memory filtering after retrieving all keys
        cur = self.conn.execute("SELECT key, expires_at FROM deriva_groups")
        now = time.time()
        result = []
        for key, expires_at in cur:
            if expires_at is not None and now >= expires_at:
                self.delete(key)
                continue
            if fnmatch.fnmatch(key, pattern):
                result.append(key)
        return result

    def scan_iter(self, pattern: str) -> Iterable[str]:
        for key in self.keys(pattern):
            yield key

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def ttl(self, key: str) -> int:
        cur = self.conn.execute("""
            SELECT expires_at FROM deriva_groups WHERE key = ?
        """, (key,))
        row = cur.fetchone()
        if not row:
            return -2  # key does not exist
        expires_at, = row
        if expires_at is None:
            return -1  # no TTL set
        remaining = int(expires_at - time.time())
        return remaining if remaining >= 0 else -2  # expired or does not exist

    def set(self, key: str, value: Union[str, bytes]) -> None:
        """Set a key-value pair without expiration (permanent storage)"""
        blob = value if isinstance(value, (bytes, bytearray)) else value.encode()
        self.conn.execute("""
            INSERT OR REPLACE INTO deriva_groups (key, value, expires_at)
            VALUES (?, ?, ?)
        """, (key, blob, None))  # None for expires_at means no expiration
        self.conn.commit()
