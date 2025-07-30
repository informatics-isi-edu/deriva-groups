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
import time
from typing import List, Optional, Dict, Tuple
from .models import Group, GroupMembership, GroupInvitation, GroupRole, InvitationStatus
from .email_service import EmailService
from ..storage.core import Storage

logger = logging.getLogger(__name__)


class GroupManager:
    def __init__(self, group_store: Storage, email_service: Optional[EmailService] = None):
        self.store = group_store
        self.email_service = email_service

    # Group management
    @staticmethod
    def can_create_group(ids: Optional[List[str]], acl_list: Optional[List[str]]) -> bool:
        """Check if any of the provided IDs match entries in the ACL list."""
        if not ids or not acl_list:
            return False
        return any(i in acl_list for i in ids if i)

    def create_group(self, name: str, description: str = "", visibility: str = "private",
                     created_by: str = "", metadata: Dict = None) -> Group:
        """Create a new group"""
        group = Group(
            id=Group.generate_id(),
            name=name,
            description=description,
            visibility=visibility,
            created_by=created_by,
            metadata=metadata or {}
        )
        self.store.create_group(group)
        return group

    def get_group(self, group_id: str) -> Optional[Group]:
        """Get a group by ID"""
        return self.store.get_group(group_id)

    def update_group(self, group_id: str, name: str = None, description: str = None,
                     visibility: str = None, metadata: Dict = None) -> Optional[Group]:
        """Update a group"""
        group = self.store.get_group(group_id)
        if not group:
            return None

        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        if visibility is not None:
            group.visibility = visibility
        if metadata is not None:
            group.metadata = metadata

        group.updated_at = time.time()
        self.store.update_group(group)
        return group

    def delete_group(self, group_id: str) -> bool:
        """Delete a group"""
        group = self.store.get_group(group_id)
        if not group:
            return False
        self.store.delete_group(group_id)
        return True

    def list_groups(self) -> List[Group]:
        """List all groups"""
        return self.store.list_groups()

    def get_user_groups(self, user_id: str) -> List[Tuple[Group, GroupMembership]]:
        """Get all groups for a user with their membership details"""
        memberships = self.store.get_user_memberships(user_id)
        result = []
        for membership in memberships:
            group = self.store.get_group(membership.group_id)
            if group:
                result.append((group, membership))
        return result

    # Membership management
    def add_member(self, group_id: str, user_id: str, user_email: str, role: GroupRole,
                   added_by: str = "", metadata: Dict = None) -> Optional[GroupMembership]:
        """Add a member to a group"""
        # Check if group exists
        group = self.store.get_group(group_id)
        if not group:
            return None

        # Check if user is already a member
        existing_membership = self.store.get_membership(group_id, user_id)
        if existing_membership:
            return None

        membership = GroupMembership(
            group_id=group_id,
            user_id=user_id,
            user_email=user_email,
            role=role,
            added_by=added_by,
            metadata=metadata or {}
        )
        self.store.add_membership(membership)
        return membership

    def update_member_role(self, group_id: str, user_id: str, new_role: GroupRole) -> Optional[GroupMembership]:
        """Update a member's role in a group"""
        membership = self.store.get_membership(group_id, user_id)
        if not membership:
            return None

        membership.role = new_role
        self.store.update_membership(membership)
        return membership

    def remove_member(self, group_id: str, user_id: str) -> bool:
        """Remove a member from a group"""
        membership = self.store.get_membership(group_id, user_id)
        if not membership:
            return False

        self.store.remove_membership(group_id, user_id)
        return True

    def get_group_members(self, group_id: str) -> List[GroupMembership]:
        """Get all members of a group"""
        return self.store.get_group_memberships(group_id)

    def get_membership(self, group_id: str, user_id: str) -> Optional[GroupMembership]:
        """Get a specific membership"""
        return self.store.get_membership(group_id, user_id)

    def check_user_role(self, group_id: str, user_id: str, required_role: GroupRole = None) -> Optional[GroupRole]:
        """Check if user has a specific role or higher in a group"""
        membership = self.store.get_membership(group_id, user_id)
        if not membership:
            return None

        if required_role is None:
            return membership.role

        # Role hierarchy: ADMINISTRATOR > MANAGER > MEMBER
        role_hierarchy = {
            GroupRole.MEMBER: 1,
            GroupRole.MANAGER: 2,
            GroupRole.ADMINISTRATOR: 3
        }

        user_level = role_hierarchy.get(membership.role, 0)
        required_level = role_hierarchy.get(required_role, 0)

        return membership.role if user_level >= required_level else None

    # Invitation management
    def create_invitation(self, group_id: str, email: str, role: GroupRole,
                          invited_by: str = "", base_url: str = "",
                          invited_by_name: str = "Administrator") -> Optional[GroupInvitation]:
        """Create and send a group invitation"""
        # Check if group exists
        group = self.store.get_group(group_id)
        if not group:
            return None

        # Check if user is already a member (by email lookup in existing memberships)
        group_members = self.store.get_group_memberships(group_id)
        for member in group_members:
            if member.user_email.lower() == email.lower():
                logger.warning(f"User {email} is already a member of group {group_id}")
                return None

        # Check for existing pending invitation
        existing_invitations = self.store.get_user_invitations(email)
        for inv in existing_invitations:
            if inv.group_id == group_id and inv.is_valid():
                logger.warning(f"User {email} already has a pending invitation to group {group_id}")
                return None

        invitation = GroupInvitation(
            id=GroupInvitation.generate_id(),
            group_id=group_id,
            group_name=group.name,
            email=email,
            role=role,
            token=GroupInvitation.generate_token(),
            invited_by=invited_by
        )

        self.store.create_invitation(invitation)
        self.send_invitation(base_url, invitation, invited_by_name)

        return invitation

    def send_invitation(self, base_url, invitation: GroupInvitation, invited_by_name) -> bool:
        if not self.email_service:
            logger.debug(f"Email service not configured or unavailable")
            return False

        if not base_url:
            logger.debug(f"Base URL not configured. Email cannot be sent")
            return False

        group_id = invitation.group_id
        email = invitation.email

        # Check if group exists
        group = self.store.get_group(group_id)
        if not group:
            logger.debug(f"Not sending email for unknown group {group_id}")
            return False

        try:
            if self.email_service.send_invitation_email(invitation, group, base_url, invited_by_name):
                logger.info(f"Invitation email sent to {email} for group {group.name}")
                return True
            else:
                invitation.status = InvitationStatus.FAILED
                return False
        except Exception as e:
            logger.error(f"Failed to send invitation email: {e}")
            invitation.status = InvitationStatus.FAILED
            return False

    def accept_invitation(self, token: str, user_id: str, user_email: str) -> Optional[GroupMembership]:
        """Accept an invitation and add user to group"""
        invitation = self.store.get_invitation_by_token(token)
        if not invitation or not invitation.is_valid():
            return None

        # Verify email matches (case insensitive)
        if invitation.email.lower() != user_email.lower():
            logger.warning(f"Email mismatch for invitation {invitation.id}: {invitation.email} != {user_email}")
            return None

        # Add user to group
        membership = self.add_member(
            group_id=invitation.group_id,
            user_id=user_id,
            user_email=user_email,
            role=invitation.role,
            added_by=invitation.invited_by,
            metadata={"invitation_id": invitation.id}
        )

        if membership:
            # Mark invitation as accepted
            invitation.status = InvitationStatus.ACCEPTED
            invitation.accepted_at = time.time()
            invitation.accepted_by = user_id
            self.store.update_invitation(invitation)

            logger.info(f"User {user_id} ({user_email}) accepted invitation to group "
                        f"{invitation.group_id} ({invitation.group_name})")

        return membership

    def revoke_invitation(self, invitation_id: str) -> bool:
        """Revoke an invitation"""
        invitation = self.store.get_invitation(invitation_id)
        if not invitation:
            return False

        invitation.status = InvitationStatus.REVOKED
        self.store.update_invitation(invitation)
        return True

    def get_group_invitations(self, group_id: str) -> List[GroupInvitation]:
        """Get all invitations for a group"""
        return self.store.get_group_invitations(group_id)

    def get_user_invitations(self, email: str) -> List[GroupInvitation]:
        """Get pending invitations for a user"""
        return self.store.get_user_invitations(email)

    def get_invitation_by_token(self, token: str) -> Optional[GroupInvitation]:
        """Get invitation by token"""
        return self.store.get_invitation_by_token(token)

    # Authorization helpers
    def user_can_manage_group(self, group_id: str, user_id: str) -> bool:
        """Check if user can manage a group (ADMINISTRATOR or MANAGER)"""
        role = self.check_user_role(group_id, user_id, GroupRole.MANAGER)
        return role is not None

    def user_can_admin_group(self, group_id: str, user_id: str) -> bool:
        """Check if user can admin a group (ADMINISTRATOR only)"""
        role = self.check_user_role(group_id, user_id, GroupRole.ADMINISTRATOR)
        return role is not None

    def user_is_member(self, group_id: str, user_id: str) -> bool:
        """Check if user is a member of a group"""
        membership = self.store.get_membership(group_id, user_id)
        return membership is not None

    # Utility methods
    def get_group_summary(self, group_id: str) -> Optional[Dict]:
        """Get a summary of group information"""
        group = self.store.get_group(group_id)
        if not group:
            return None

        members = self.store.get_group_memberships(group_id)
        invitations = self.store.get_group_invitations(group_id)
        pending_invitations = [inv for inv in invitations if inv.is_valid()]

        # Count members by role
        role_counts = {role.value: 0 for role in GroupRole}
        for member in members:
            role_counts[member.role.value] += 1

        return {
            "group": group.to_dict(),
            "member_count": len(members),
            "pending_invitations": len(pending_invitations),
            "role_distribution": role_counts,
            "recent_members": [m.to_dict() for m in sorted(members, key=lambda x: x.joined_at, reverse=True)[:5]]
        }
