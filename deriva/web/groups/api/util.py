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
import requests
import json
import time
import hashlib
import logging
from functools import wraps
from flask import current_app, request, g, abort, Response
from typing import Optional, Dict, Any
from .storage.core import Storage


logger = logging.getLogger(__name__)

def make_json_response(data):
    return Response(
        json.dumps(data, sort_keys=False),  # Preserve key order
        mimetype="application/json"
    )


def is_browser_client(request): # pragma: no cover
    has_cookie = current_app.config["COOKIE_NAME"] in request.cookies
    accept_html = "text/html" in request.headers.get("Accept", "")
    ua = request.headers.get("User-Agent", "").lower()
    ua_looks_browser = any(x in ua for x in ["mozilla", "chrome", "safari", "edge", "firefox"])

    return has_cookie and (accept_html or ua_looks_browser)


class SessionManager:
    """Session cache for authentication"""

    def __init__(self, storage: Storage, auth_base_url: str, cache_ttl: int = 300):
        """
        Initialize session manager

        Args:
            storage: Initialized Storage instance
            auth_base_url: Base URL for auth service (e.g., '/authn')
            cache_ttl: Cache TTL in seconds (default 5 minutes)
        """
        self.storage = storage
        self.auth_base_url = auth_base_url.rstrip('/')
        self.cache_ttl = cache_ttl
        self.refresh_threshold = cache_ttl * 0.8  # Refresh at 80% of TTL

    @staticmethod
    def _generate_cache_key(token: str) -> str:
        """Generate consistent cache key from token"""
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _extract_authorization() -> (str, bool):
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            return auth.split(" ", 1)[1], True
        cookie_name = current_app.config["COOKIE_NAME"]
        cookie_val = request.cookies.get(cookie_name)
        return cookie_val, False

    def _fetch_session_from_auth_service(self) -> Optional[Dict[str, Any]]:
        """Fetch session info from auth service"""
        try:
            headers = {}
            cookies = {}

            # Determine auth method
            auth, is_token = self._extract_authorization()
            if is_token:
                headers['Authorization'] = f'Bearer {auth}'
            else:
                cookie_name = current_app.config["COOKIE_NAME"]
                cookies[cookie_name] = auth

            verify = current_app.config.get("AUTH_ALLOW_BYPASS_CERT_VERIFY", False)
            response = requests.get(
                f"{self.auth_base_url}/session",
                headers=headers,
                cookies=cookies,
                timeout=5,
                verify=not verify
            )

            if response.status_code == 200:
                session_data = response.json()
                # logger.debug(f"Fetched session: {session_data}")
                return session_data
            elif response.status_code == 404:
                logger.debug("Auth service returned 404 - invalid session")
                return None
            else:
                logger.warning(f"Auth service returned {response.status_code}")
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to contact auth service: {e}")
            return None

    def _extend_session_at_auth_service(self) -> Optional[Dict[str, Any]]:
        """Extend a session with the auth service"""
        try:
            headers = {}
            cookies = {}

            # Determine auth method
            auth, is_token = self._extract_authorization()
            if is_token:
                headers['Authorization'] = f'Bearer {auth}'
            else:
                cookie_name = current_app.config["COOKIE_NAME"]
                cookies[cookie_name] = auth

            verify = current_app.config.get("AUTH_ALLOW_BYPASS_CERT_VERIFY", False)
            response = requests.put(
                f"{self.auth_base_url}/session?refresh_upstream=true",
                headers=headers,
                cookies=cookies,
                timeout=5,
                verify=not verify
            )

            if response.status_code == 200:
                session_data = response.json()
                # logger.debug(f"Fetched session: {session_data}")
                return session_data
            elif response.status_code == 404:
                logger.debug("Auth service returned 404 - invalid session")
                return None
            else:
                logger.warning(f"Auth service returned {response.status_code}")
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to contact auth service: {e}")
            return None

    def _validate_session_active(self) -> bool:
        """Lightweight check if session is still active"""
        try:
            headers = {}
            cookies = {}

            # Determine auth method
            auth, is_token = self._extract_authorization()
            if is_token:
                headers['Authorization'] = f'Bearer {auth}'
            else:
                cookie_name = current_app.config["COOKIE_NAME"]
                cookies[cookie_name] = auth

            response = requests.head(
                f"{self.auth_base_url}/session",
                headers=headers,
                cookies=cookies,
                timeout=3
            )

            return response.status_code == 200

        except requests.RequestException:
            return False

    def get_user_session(self) -> Optional[Dict[str, Any]]:
        """
        Get user session with caching

        Returns:
            User session data or None if invalid
        """
        auth, is_token = self._extract_authorization()
        if not auth:
            return None

        cache_key = self._generate_cache_key(auth)

        try:
            # Try to get from cache
            cached_data = self.storage.get_session(cache_key)

            if cached_data:
                cached_at = cached_data.get('cached_at', 0)
                age = time.time() - cached_at

                # If cache is fresh, return immediately
                if age < self.refresh_threshold:
                    return cached_data['session_data']

                # If cache exists but getting old, validate and refresh while it's still active
                if age < self.cache_ttl:
                    if self._validate_session_active():
                        logger.debug(f"Cache refreshing: {cache_key}")
                        self._extend_session_at_auth_service()
                    else:
                        # Session was revoked, invalidate cache
                        logger.info(f"Session revoked, invalidating cache: {cache_key}")
                        self.invalidate_session(cache_key)
                        return None

            # Cache miss or expired - fetch from auth service
            logger.debug(f"Cache miss, fetching from auth service: {cache_key}")
            session_data = self._fetch_session_from_auth_service()

            if session_data:
                # Cache the session data
                cache_data = {
                    'session_data': session_data,
                    'cached_at': time.time()
                }
                self.storage.set_session(cache_key, cache_data, self.cache_ttl)

                #logger.debug(f"Cached session data: {cache_key}")
                return session_data

            return None

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            # Invalidate corrupted cache entry
            self.storage.delete_session(cache_key)
            return self._fetch_session_from_auth_service()
        except Exception as e:
            logger.error(f"Storage error: {e}")
            # Fall back to direct auth service call
            return self._fetch_session_from_auth_service()


    def invalidate_session(self, cache_key: str) -> bool:
        """
        Invalidate cached session

        Args:
            cache_key: the cache key

        Returns:
            True if invalidation was successful
        """
        if not cache_key:
            return False

        try:
            self.storage.delete_session(cache_key)
            logger.info(f"Invalidated session cache: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate session: {e}")
            return False

# Decorator
def require_auth(f):
    """
    Decorator to require authentication for Flask routes

    Usage:
        @app.route('/protected')
        @require_auth
        def protected_route():
            user = g.current_user
            return jsonify({'user_id': user['sub']})
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_manager = current_app.config["SESSION_MANAGER"]

        # Get user session
        user_session = session_manager.get_user_session()

        if not user_session:
            abort(401, "Invalid or expired session")

        # Store in Flask's g object for use in route
        g.current_user = user_session
        if current_app.config.get("ENABLE_LEGACY_AUTH_API", False):
            client = user_session.get("client")
            g.user_id = client.get("id")
            g.user_email = client.get("email")
            g.user_name = client.get("full_name")
        else:
            sub = user_session.get("sub")
            iss = user_session.get("iss")
            g.user_id =  iss + "/" + user_session.get("sub") if iss else sub
            g.user_email = user_session.get("email")
            g.user_name = user_session.get("name")

        return f(*args, **kwargs)

    return decorated_function
