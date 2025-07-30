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

groups_blueprint = Blueprint("groups", __name__)

def get_group_manager():
    """Get the group manager from the current app"""
    return current_app.config["GROUP_MANAGER"]

def get_join_request_manager():
    """Get the join request manager from the current app"""
    return current_app.config["JOIN_REQUEST_MANAGER"]

@groups_blueprint.route("/groups", methods=["GET"])
@require_auth
def list_groups():
    """List all groups"""
    group_manager = get_group_manager()

    groups = group_manager.list_groups()
    groups_data = []
    for group in groups:
        group_dict = group.to_dict()
        # Add membership info if user is a member
        membership = group_manager.get_membership(group.id, g.user_id)
        if membership:
            group_dict["membership"] = membership.to_dict()
        # Add member count
        members = group_manager.get_group_members(group.id)
        group_dict["member_count"] = len(members)
        groups_data.append(group_dict)

    return make_json_response({"groups": groups_data})

@groups_blueprint.route("/groups/my", methods=["GET"])
@require_auth
def my_groups():
    """List all groups filtered by user membership"""
    group_manager = get_group_manager()

    user_groups = group_manager.get_user_groups(g.user_id)
    groups_data = []
    for group, membership in user_groups:
        group_dict = group.to_dict()
        group_dict["membership"] = membership.to_dict()
        # Add member count
        members = group_manager.get_group_members(group.id)
        group_dict["member_count"] = len(members)
        groups_data.append(group_dict)

    return make_json_response({"groups": groups_data})


@groups_blueprint.route("/groups", methods=["POST"])
@require_auth
def create_group():
    """Create a new group"""
    group_manager = get_group_manager()

    data = request.get_json()
    if not data:
        abort(400, "JSON data required")

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    visibility = data.get("visibility", "private").strip()  # Default to private
    metadata = data.get("metadata", {})

    if not name:
        abort(400, "Group name is required")

    # Validate visibility
    if visibility not in ["public", "private"]:
        abort(400, "Visibility must be 'public' or 'private'")

    # Check if group creation is permitted
    ids = [g.user_id]
    user_groups = group_manager.get_user_groups(g.user_id)
    ids.extend([group[0].id for group in user_groups])
    acl_list = current_app.config["GROUPS_CONFIG"].get("create_group_acl", [])
    if not group_manager.can_create_group(ids, acl_list):
        abort(403, "Group creation not permitted")

    # Create group
    group = group_manager.create_group(
        name=name,
        description=description,
        visibility=visibility,
        created_by=g.user_id,
        metadata=metadata
    )

    # Add creator as administrator
    membership = group_manager.add_member(
        group_id=group.id,
        user_id=g.user_id,
        user_email=g.user_email,
        role=GroupRole.ADMINISTRATOR,
        added_by=g.user_id
    )

    audit_event("group_created", user=g.user_email, id=g.user_id, group_id=group.id, group_name=group.name)

    result = group.to_dict()
    result["membership"] = membership.to_dict() if membership else None

    return make_json_response(result), 201


@groups_blueprint.route("/groups/<group_id>", methods=["GET"])
@require_auth
def get_group(group_id):
    """Get a specific group"""
    group_manager = get_group_manager()

    group = group_manager.get_group(group_id)
    if not group:
        abort(404, "Group not found")

    # Check if user is a member or if group is publicly viewable
    membership = group_manager.get_membership(group_id, g.user_id)
    if not membership:
        # For now, require membership to view group details
        abort(403, "Access denied")

    result = group.to_dict()
    result["membership"] = membership.to_dict()

    # Include additional details if user can manage the group
    if group_manager.user_can_manage_group(group_id, g.user_id):
        summary = group_manager.get_group_summary(group_id)
        if summary:
            result.update({
                "member_count": summary["member_count"],
                "pending_invitations": summary["pending_invitations"],
                "role_distribution": summary["role_distribution"]
            })

    return make_json_response(result)


@groups_blueprint.route("/groups/<group_id>", methods=["PUT"])
@require_auth
def update_group(group_id):
    """Update a group"""
    group_manager = get_group_manager()

    # Check if user can admin the group
    if not group_manager.user_can_admin_group(group_id, g.user_id):
        abort(403, "Administrator access required")

    data = request.get_json()
    if not data:
        abort(400, "JSON data required")

    name = data.get("name", "").strip() if "name" in data else None
    description = data.get("description", "").strip() if "description" in data else None
    visibility = data.get("visibility", "").strip() if "visibility" in data else None
    metadata = data.get("metadata") if "metadata" in data else None

    if name is not None and not name:
        abort(400, "Group name cannot be empty")

    # Validate visibility if provided
    if visibility is not None and visibility not in ["public", "private"]:
        abort(400, "Visibility must be 'public' or 'private'")

    group = group_manager.update_group(group_id, name, description, visibility, metadata)
    if not group:
        abort(404, "Group not found")

    audit_event("group_updated", user=g.user_email, id=g.user_id,
                group_id=group_id, group_name=group.name)

    return make_json_response(group.to_dict())


@groups_blueprint.route("/groups/<group_id>", methods=["DELETE"])
@require_auth
def delete_group(group_id):
    """Delete a group"""
    group_manager = get_group_manager()

    # Check if user can admin the group
    if not group_manager.user_can_admin_group(group_id, g.user_id):
        abort(403, "Administrator access required")

    group = group_manager.get_group(group_id)
    if not group:
        abort(404, "Group not found")

    group_name = group.name
    success = group_manager.delete_group(group_id)

    if success:
        audit_event("group_deleted", user=g.user_email, id=g.user_id,
                    group_id=group_id, group_name=group_name)
        return make_json_response({"status": "deleted"})
    else:
        abort(500, "Failed to delete group")


@groups_blueprint.route("/groups/<group_id>/members", methods=["GET"])
@require_auth
def get_group_members(group_id):
    """Get group members"""
    group_manager = get_group_manager()

    # Check if user is a member
    if not group_manager.user_is_member(group_id, g.user_id):
        abort(403, "Group membership required")

    members = group_manager.get_group_members(group_id)
    members_data = [member.to_dict() for member in members]

    return make_json_response({"members": members_data})


@groups_blueprint.route("/groups/<group_id>/members", methods=["POST"])
@require_auth
def add_group_member(group_id):
    """Add a member to a group"""
    group_manager = get_group_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    data = request.get_json()
    if not data:
        abort(400, "JSON data required")

    member_user_id = data.get("user_id", "").strip()
    member_email = data.get("email", "").strip()
    role_str = data.get("role", "member").lower()

    if not member_user_id or not member_email:
        abort(400, "user_id and email are required")

    try:
        role = GroupRole(role_str)
    except ValueError:
        abort(400, "Invalid role")

    # Only administrators can add other administrators
    if role == GroupRole.ADMINISTRATOR and not group_manager.user_can_admin_group(group_id, g.user_id):
        abort(403, "Administrator access required to assign administrator role")

    membership = group_manager.add_member(group_id, member_user_id, member_email, role, g.user_id)
    if not membership:
        abort(400, "Failed to add member (user may already be a member or group may not exist)")

    audit_event("member_added", user=g.user_email, id=g.user_id,
                group_id=group_id, member_user_id=member_user_id, member_email=member_email, role=role.value)

    return make_json_response(membership.to_dict()), 201


@groups_blueprint.route("/groups/<group_id>/members", methods=["PUT"])
@require_auth
def update_group_member(group_id):
    """Update a group member's role"""

    group_manager = get_group_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    data = request.get_json()
    if not data:
        abort(400, "JSON data required")

    member_user_id = data.get("user_id", "").strip()
    role_str = data.get("role", "").lower()
    try:
        new_role = GroupRole(role_str)
    except ValueError:
        abort(400, "Invalid role")

    # Only administrators can assign administrator roles
    if new_role == GroupRole.ADMINISTRATOR and not group_manager.user_can_admin_group(group_id, g.user_id):
        abort(403, "Administrator access required to assign administrator role")

    # Prevent users from demoting themselves if they're the only admin
    if member_user_id == g.user_id and new_role != GroupRole.ADMINISTRATOR:
        members = group_manager.get_group_members(group_id)
        admin_count = sum(1 for m in members if m.role == GroupRole.ADMINISTRATOR)
        if admin_count <= 1:
            abort(400, "Cannot demote the only administrator")

    membership = group_manager.update_member_role(group_id, member_user_id, new_role)
    if not membership:
        abort(404, "Member not found")

    audit_event("member_role_updated", user=g.user_email, id=g.user_id,
                group_id=group_id, member_user_id=member_user_id, new_role=new_role.value)

    return make_json_response(membership.to_dict())


@groups_blueprint.route("/groups/<group_id>/members", methods=["DELETE"])
@require_auth
def remove_group_member(group_id):
    """Remove a member from a group"""

    group_manager = get_group_manager()

    data = request.get_json()
    if not data:
        abort(400, "JSON data required")

    member_user_id = data.get("user_id", "").strip()

    # Check if user can manage the group or is removing themselves
    if not (group_manager.user_can_manage_group(group_id, g.user_id) or member_user_id == g.user_id):
        abort(403, "Manager access required or can only remove yourself")

    # Prevent removing the only administrator
    if member_user_id != g.user_id:  # Only check if removing someone else
        membership = group_manager.get_membership(group_id, member_user_id)
        if membership and membership.role == GroupRole.ADMINISTRATOR:
            members = group_manager.get_group_members(group_id)
            admin_count = sum(1 for m in members if m.role == GroupRole.ADMINISTRATOR)
            if admin_count <= 1:
                abort(400, "Cannot remove the only administrator")

    success = group_manager.remove_member(group_id, member_user_id)
    if not success:
        abort(404, "Member not found")

    audit_event("member_removed", user=g.user_email, id=g.user_id,
                group_id=group_id, member_user_id=member_user_id)

    return make_json_response({"status": "removed"})


@groups_blueprint.route("/groups/<group_id>/invitations", methods=["GET"])
@require_auth
def get_group_invitations(group_id):
    """Get group invitations"""

    group_manager = get_group_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    invitations = group_manager.get_group_invitations(group_id)
    invitations_data = [inv.to_dict() for inv in invitations]

    return make_json_response({"invitations": invitations_data})


@groups_blueprint.route("/groups/<group_id>/invitations", methods=["POST"])
@require_auth
def create_group_invitation(group_id):
    """Create a group invitation"""

    group_manager = get_group_manager()
    group = group_manager.get_group(group_id)
    if not group:
        abort(404, "Group not found")

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    data = request.get_json()
    if not data:
        abort(400, "JSON data required")

    email = data.get("email", "").strip().lower()
    role_str = data.get("role", "member").lower()

    if not email:
        abort(400, "Email is required")

    try:
        role = GroupRole(role_str)
    except ValueError:
        abort(400, "Invalid role")

    # Only administrators can invite other administrators
    if role == GroupRole.ADMINISTRATOR and not group_manager.user_can_admin_group(group_id, g.user_id):
        abort(403, "Administrator access required to invite administrators")

    base_url = current_app.config.get("APP_BASE_URL", "")
    invited_by_name = g.user_name or "Administrator"

    invitation = group_manager.create_invitation(
        group_id=group_id,
        email=email,
        role=role,
        invited_by=g.user_id,
        base_url=base_url,
        invited_by_name=invited_by_name
    )

    if not invitation:
        abort(400, "Failed to create invitation (user may already be a member or have pending invitation)")

    logger.debug(f"Invitation created: {invitation}")
    if invitation.status == InvitationStatus.FAILED:
        abort(502, "Failed to send invitation email. Contact system administrator.")

    audit_event("invitation_created", user=g.user_email, id=g.user_id,
                group_id=group_id, invitation_email=email, role=role.value)

    return make_json_response(invitation.to_dict()), 201


@groups_blueprint.route("/groups/<group_id>/invitations/<invitation_id>", methods=["DELETE"])
@require_auth
def revoke_group_invitation(group_id, invitation_id):
    """Revoke a group invitation"""

    group_manager = get_group_manager()

    # Check if user can manage the group
    if not group_manager.user_can_manage_group(group_id, g.user_id):
        abort(403, "Manager access required")

    success = group_manager.revoke_invitation(invitation_id)
    if not success:
        abort(404, "Invitation not found")

    audit_event("invitation_revoked", user=g.user_email, id=g.user_id,
                group_id=group_id, invitation_id=invitation_id)

    return make_json_response({"status": "revoked"})


@groups_blueprint.route("/invitations/pending", methods=["GET"])
@require_auth
def get_user_pending_invitations():
    """Get pending invitations for the current user"""

    group_manager = get_group_manager()

    invitations = group_manager.get_user_invitations(g.user_email)
    invitations_data = []

    for invitation in invitations:
        inv_dict = invitation.to_dict()
        # Add group info
        group = group_manager.get_group(invitation.group_id)
        if group:
            inv_dict["group"] = group.to_dict()
        invitations_data.append(inv_dict)

    return make_json_response({"invitations": invitations_data})


@groups_blueprint.route("/invitations/<token>/accept", methods=["POST"])
@require_auth
def accept_invitation(token):
    """Accept an invitation via token"""

    group_manager = get_group_manager()

    membership = group_manager.accept_invitation(token, g.user_id, g.user_email)
    if not membership:
        abort(400, "Invalid or expired invitation")

    audit_event("invitation_accepted", user=g.user_email, id=g.user_id,
                group_id=membership.group_id, role=membership.role.value)

    # Return membership with group info
    result = membership.to_dict()
    group = group_manager.get_group(membership.group_id)
    if group:
        result["group"] = group.to_dict()

    return make_json_response(result)


@groups_blueprint.route("/invitations/<token>", methods=["GET"])
@require_auth
def get_invitation_info(token):
    """Get information about an invitation (public endpoint for email links)"""
    group_manager = get_group_manager()

    invitation = group_manager.get_invitation_by_token(token)
    if not invitation or not invitation.is_valid():
        abort(404, "Invalid or expired invitation")

    # Return limited information
    group = group_manager.get_group(invitation.group_id)
    result = {
        "group_name": group.name if group else "Unknown Group",
        "group_description": group.description if group else "",
        "role": invitation.role.value,
        "expires_at": invitation.expires_at,
        "is_valid": invitation.is_valid()
    }

    return make_json_response(result)


# Public endpoints (no authentication required)

@groups_blueprint.route("/groups/<group_id>/public", methods=["GET"])
def get_public_group_info(group_id):
    """Get public information about a group (no authentication required)"""
    group_manager = get_group_manager()
    if not group_manager:
        abort(500, "Group management not configured")

    group = group_manager.get_group(group_id)
    if not group:
        abort(404, "Group not found")

    # Only return info for public groups
    if group.visibility != "public":
        abort(403, "This group is private")

    # Return basic public information
    result = {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "visibility": group.visibility,
        "created_at": group.created_at,
        "member_count": len(group_manager.get_group_members(group_id))
    }

    return make_json_response(result)
