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
import os
import json
import logging
from pathlib import Path
from dotenv import dotenv_values
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from .rest.groups import groups_blueprint
from .rest.join_requests import join_requests_blueprint
from .telemetry.metrics.prometheus import metrics_blueprint
from .telemetry.audit.logger import init_audit_logger
from .api.storage.core import Storage, create_storage_backend
from .api.groups.group_manager import GroupManager
from .api.groups.join_request_manager import JoinRequestManager
from .api.groups.email_service import create_email_service_from_config
from .api.groups.common import NotificationService
from .api.util import SessionManager

logger = logging.getLogger(__name__)

def load_config(app):
    """
    Load app.config with DERIVA_GROUPS_* variables from OS environment, .env file, else sane defaults.
    """
    # Defaults for any missing DERIVA_GROUPS_* vars
    env_config = {
        "DERIVA_GROUPS_STORAGE_BACKEND": "memory",
        "DERIVA_GROUPS_CORS_ORIGINS": "",
        "DERIVA_GROUPS_AUDIT_USE_SYSLOG": "false",
        "DERIVA_GROUPS_AUDIT_LOGFILE_PATH": "/var/log/deriva-groups-audit.log"
    }

    # Load .env from one of these locations, if it exists
    dotenv_locations = [
        Path("/etc/deriva/deriva_groups.env"),
        Path.home() / "deriva_groups.env",
        Path("./config/deriva_groups.env"),
        Path("./deriva_groups.env")
    ]
    for fn in dotenv_locations:
        if fn.is_file():
            fp = str(fn)
            env_config.update(dotenv_values(dotenv_path=fp))
            logger.info(f"Loaded dotenv configuration file from: {fp}")
            break

    env_config.update(os.environ.items())

    _ENV_PREFIX = "DERIVA_GROUPS_"
    app.config.update({
        # strip _ENV_PREFIX from env keys
        (k[len(_ENV_PREFIX):], v)
        for k, v in env_config.items()
        if k.startswith(_ENV_PREFIX)
    })

    legacy_mode = app.config.get("ENABLE_LEGACY_AUTH_API", False)
    if not app.config.get("COOKIE_NAME"):
        app.config["COOKIE_NAME"] = "credenza" if not legacy_mode else "webauthn"


def create_app():
    app = Flask(__name__)
    load_config(app)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", force=True)
    logging.getLogger("deriva.web.groups").setLevel(
        logging.DEBUG if app.config.get("DERIVA_GROUPS_DEBUG", app.config.get("DEBUG", False)) else logging.INFO)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        response = e.get_response()
        response.data = jsonify({
            "error": e.name.lower().replace(" ", "_"),
            "code": e.code,
            "message": e.description,
        }).data
        response.content_type = "application/json"
        return response

    @app.after_request
    def apply_secure_headers(response):
        if app.config["COOKIE_NAME"] in request.cookies:
            response.headers["Cache-Control"] = "private, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    # Load / merge config
    load_config(app)

    init_audit_logger(filename=app.config.get("AUDIT_LOGFILE_PATH", "deriva-groups-audit.log"),
                      use_syslog=app.config.get("AUDIT_USE_SYSLOG", False))

    # Service-specific initialization
    init_group_management(app)

    # Setup CORS
    setup_cors(app)

    if app.config.get("ENABLE_HEALTH_CHECK", True):
        enable_healthcheck(app)

    return app

def init_group_management(app):
    # Initialize group management
    storage_backend = create_storage_backend(app.config.get("STORAGE_BACKEND", "memory"),
                                             url=app.config.get("STORAGE_BACKEND_URL"))
    storage = Storage(storage_backend)

    auth_base_url = app.config.get('AUTH_BASE_URL', '/authn')
    cache_ttl = app.config.get('SESSION_CACHE_TTL', 1800)

    session_manager = SessionManager(storage, auth_base_url, cache_ttl)
    app.config["SESSION_MANAGER"] = session_manager
    logger.debug(f"Session manager initialized")

    email_service = None
    notification_service = None

    groups_config_path = app.config.get("GROUPS_CONFIG_FILE", "config/groups_config.json")
    if os.path.exists(groups_config_path):
        with open(groups_config_path) as f:
            groups_config = app.config["GROUPS_CONFIG"] = json.load(f)
    else:
        groups_config = app.config["GROUPS_CONFIG"] = {}

    if "email_service" in groups_config:
        email_service_config = groups_config["email_service"]
        email_service_secrets_file = groups_config["email_service_secrets_file"]
        if os.path.exists(email_service_secrets_file):
            with open(email_service_secrets_file) as f:
                email_secrets = json.load(f)
                email_service_config.update(email_secrets)
        else:
            logger.warning(f"Email service secrets file {email_service_secrets_file} does not exist")

        logger.debug("Email service configuration found. Creating service and testing connection...")
        email_service = create_email_service_from_config(email_service_config)
        if email_service:
            if not email_service.test_connection():
                logger.warning(f"Email service connection test failed")
            else:
                notification_service = NotificationService(email_service)

    if email_service:
        logger.info("Email service successfully configured for group invitations and join request notifications")
    else:
        logger.warning(
            "Email service not configured - group invitations and join request notifications will not be sent")

    app.config["GROUP_STORAGE"] = storage
    app.config["GROUP_MANAGER"] = GroupManager(storage, email_service)
    app.config["JOIN_REQUEST_MANAGER"] = JoinRequestManager(storage, notification_service)

    app.register_blueprint(groups_blueprint)
    app.register_blueprint(join_requests_blueprint)
    app.register_blueprint(metrics_blueprint)


def setup_cors(app):
    """Setup CORS for frontend communication"""
    
    # Get allowed origins from environment variable
    cors_origins = app.config.get('CORS_ORIGINS', '').strip()
    
    if cors_origins:
        # Parse comma-separated origins
        allowed_origins = [origin.strip() for origin in cors_origins.split(',') if origin.strip()]
        logger.info(f"CORS configured for origins: {allowed_origins}")
        CORS(app, origins=allowed_origins, supports_credentials=True)
    else:
        # Development fallback - allow common localhost ports
        default_origins = ["http://localhost", "https://localhost"]
        logger.info(f"CORS configured with default development origins: {default_origins}")
        CORS(app, origins=default_origins, supports_credentials=True)


def enable_healthcheck(app):
    @app.route('/health')
    def health_check():
        """Health check endpoint for load balancers or other orchestration"""
        return jsonify({"status": "healthy", "service": "deriva-groups"}), 200


if __name__ == "__main__":
    application = create_app()
    port = application.config.get("SERVER_PORT", 8999)
    application.run(host="0.0.0.0", port=port)
