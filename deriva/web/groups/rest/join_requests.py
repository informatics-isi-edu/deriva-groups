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

import logging
from flask import Blueprint, request, current_app, abort, g
from ...groups.api.util import make_json_response, require_auth
from ...groups.api.groups.models import GroupRole, InvitationStatus
from ...groups.telemetry import audit_event

logger = logging.getLogger(__name__)

join_requests_blueprint = Blueprint("join_requests", __name__)

def get_join_request_manager():
    """Get the join request manager from the current app"""
    return current_app.config.get("JOIN_REQUEST_MANAGER")


def get_group_manager():
    """Get the group manager from the current app"""
    return current_app.config.get("GROUP_MANAGER")


@join_requests_blueprint.route("/groups/<group_id>/join-requests", methods=["GET"])
@require_auth
def get_group_join_requests(group_id):
    """Get join requests for a group (admin/manager access required)"""

    group_manager = get_group_manager()
    join_request_manager = get_join_request_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    pending_only = request.args.get("pending_only", "true").lower() == "true"
    join_requests = join_request_manager.get_group_join_requests(group_id, pending_only)

    requests_data = []
    for join_request in join_requests:
        request_dict = join_request.to_dict()
        # Add group info if available
        group = group_manager.get_group(group_id)
        if group:
            request_dict["group"] = {"name": group.name, "description": group.description}
        requests_data.append(request_dict)

    return make_json_response({"join_requests": requests_data})


@join_requests_blueprint.route("/groups/<group_id>/join-requests/<request_id>/approve", methods=["POST"])
@require_auth
def approve_join_request(group_id, request_id):
    """Approve a join request"""

    group_manager = get_group_manager()
    join_request_manager = get_join_request_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    data = request.get_json() or {}
    role_str = data.get("role", "member").lower()
    reviewer_comment = data.get("comment", "").strip()

    try:
        role = GroupRole(role_str)
    except ValueError:
        abort(400, "Invalid role")

    # Only administrators can assign administrator roles
    if role == GroupRole.ADMINISTRATOR and not group_manager.user_can_admin_group(group_id, g.user_id):
        abort(403, "Administrator access required to assign administrator role")

    # Get the join request
    join_request = join_request_manager.get_join_request(request_id)
    if not join_request or join_request.group_id != group_id:
        abort(404, "Join request not found")

    # Approve the request
    success, error = join_request_manager.approve_join_request(request_id, g.user_id, g.user_name, role, reviewer_comment)
    if not success:
        abort(400, error)

    # Add user to group
    membership = group_manager.add_member(
        group_id=group_id,
        user_id=join_request.user_id,
        user_email=join_request.user_email,
        role=role,
        added_by=g.user_id,
        metadata={"source": "join_request", "request_id": request_id}
    )

    if not membership:
        abort(500, "Failed to add user to group after approval")

    audit_event("join_request_approved", user=g.user_email, id=g.user_id,
                group_id=group_id, request_id=request_id, requester_email=join_request.user_email, role=role.value)

    # Return the updated request and new membership
    updated_request = join_request_manager.get_join_request(request_id)
    result = updated_request.to_dict() if updated_request else {}
    result["membership"] = membership.to_dict()

    return make_json_response(result)


@join_requests_blueprint.route("/groups/<group_id>/join-requests/<request_id>/deny", methods=["POST"])
@require_auth
def deny_join_request(group_id, request_id):
    """Deny a join request"""

    group_manager = get_group_manager()
    join_request_manager = get_join_request_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    data = request.get_json() or {}
    reviewer_comment = data.get("comment", "").strip()

    # Get the join request
    join_request = join_request_manager.get_join_request(request_id)
    if not join_request or join_request.group_id != group_id:
        abort(404, "Join request not found")

    # Deny the request
    success, error = join_request_manager.deny_join_request(request_id, g.user_id, g.user_name, reviewer_comment)
    if not success:
        abort(400, error)

    audit_event("join_request_denied", user=g.user_email, id=g.user_id,
                group_id=group_id, request_id=request_id, requester_email=join_request.user_email)

    # Return the updated request
    updated_request = join_request_manager.get_join_request(request_id)
    return make_json_response(updated_request.to_dict() if updated_request else {})


@join_requests_blueprint.route("/join-requests/my", methods=["GET"])
@require_auth
def get_my_join_requests():
    """Get current user's join requests"""

    join_request_manager = get_join_request_manager()
    group_manager = get_group_manager()

    join_requests = join_request_manager.get_user_join_requests(g.user_id)

    requests_data = []
    for join_request in join_requests:
        request_dict = join_request.to_dict()
        # Add group info
        group = group_manager.get_group(join_request.group_id)
        if group:
            request_dict["group"] = group.to_dict()
        requests_data.append(request_dict)

    return make_json_response({"join_requests": requests_data})


@join_requests_blueprint.route("/join-requests/<request_id>/cancel", methods=["POST"])
@require_auth
def cancel_join_request(request_id):
    """Cancel a join request (by the user who created it)"""

    join_request_manager = get_join_request_manager()

    success, error = join_request_manager.cancel_join_request(request_id, g.user_id)
    if not success:
        abort(400, error)

    audit_event("join_request_cancelled", user=g.user_email, id=g.user_id,
                request_id=request_id)

    return make_json_response({"status": "cancelled"})


@join_requests_blueprint.route("/groups/<group_id>/request-to-join", methods=["POST"])
@require_auth
def create_join_request(group_id):
    """Create a join request for a group"""

    group_manager = get_group_manager()
    join_request_manager = get_join_request_manager()

    # Check if group exists
    group = group_manager.get_group(group_id)
    if not group:
        abort(404, "Group not found")

    # Check if user is already a member
    if group_manager.user_is_member(group_id, g.user_id):
        abort(400, "You are already a member of this group")

    # Check if user already has a pending request
    if join_request_manager.has_pending_request(group_id, g.user_id):
        abort(400, "You already have a pending request to join this group")

    data = request.get_json() or {}
    message = data.get("message", "").strip()

    base_url = current_app.config.get("APP_BASE_URL", "")

    # Create the join request
    join_request = join_request_manager.create_join_request(
        group_id=group_id,
        group_name=group.name,
        user_id=g.user_id,
        user_email=g.user_email,
        user_name=g.user_name,
        message=message,
        base_url=base_url
    )

    if not join_request:
        abort(500, "Failed to create join request")

    audit_event("join_request_created", user=g.user_email, id=g.user_id,
                group_id=group_id, request_id=join_request.id)

    # Return the join request with group info
    result = join_request.to_dict()
    result["group"] = group.to_dict()

    return make_json_response(result), 201


# Public endpoints (no authentication required)

@join_requests_blueprint.route("/join/<token>", methods=["GET"])
def get_join_info(token):
    """Get information about a join request (public endpoint)"""
    join_request_manager = get_join_request_manager()
    group_manager = get_group_manager()

    join_info = join_request_manager.get_public_join_info(token)
    if not join_info:
        abort(404, "Invalid or expired join request")

    # Add group information
    group = group_manager.get_group(join_info["group_id"])
    if group:
        result = {
            "group_name": group.name,
            "group_description": group.description,
            "is_valid": join_info["is_valid"],
            "expires_at": join_info["expires_at"]
        }
    else:
        result = {
            "group_name": "Unknown Group",
            "group_description": "",
            "is_valid": False,
            "expires_at": join_info["expires_at"]
        }

    return make_json_response(result)


@join_requests_blueprint.route("/join/<token>", methods=["POST"])
def request_to_join_via_token(token):
    """Create a join request via public token (requires authentication)"""

    join_request_manager = get_join_request_manager()
    group_manager = get_group_manager()

    join_info = join_request_manager.get_public_join_info(token)
    if not join_info or not join_info["is_valid"]:
        abort(404, "Invalid or expired join request")

    group_id = join_info["group_id"]

    # Check if group exists
    group = group_manager.get_group(group_id)
    if not group:
        abort(404, "Group not found")

    # Check if user is already a member
    if group_manager.user_is_member(group_id, g.user_id):
        abort(400, "You are already a member of this group")

    # Check if user already has a pending request
    if join_request_manager.has_pending_request(group_id, g.user_id):
        abort(400, "You already have a pending request to join this group")

    data = request.get_json() or {}
    message = data.get("message", "").strip()

    base_url = current_app.config.get("APP_BASE_URL", "")

    # Create the join request
    join_request = join_request_manager.create_join_request(
        group_id=group_id,
        user_id=g.user_id,
        user_email=g.user_email,
        user_name=g.user_name,
        message=message,
        base_url=base_url
    )

    if not join_request:
        abort(500, "Failed to create join request")

    audit_event("join_request_created_via_token", user=g.user_email, id=g.user_id,
                group_id=group_id, request_id=join_request.id, token=token)

    # Return the join request with group info
    result = join_request.to_dict()
    result["group"] = group.to_dict()

    return make_json_response(result), 201