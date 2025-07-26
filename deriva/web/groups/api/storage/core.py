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

import json
import logging
import time
from typing import List, Optional
from dataclasses import asdict
from werkzeug.utils import import_string
from .backends import STORAGE_BACKENDS
from .backends.base import StorageBackend
from .backends.memory import MemoryBackend
from ..groups.models import Group, GroupMembership, GroupInvitation, InvitationStatus, JoinRequest, JoinRequestStatus

logger = logging.getLogger(__name__)


def _prepare_for_json(obj):
    """Convert dataclass to dict and handle enum serialization"""
    data = asdict(obj)
    # Convert any enum values to their string values
    for key, value in data.items():
        if hasattr(value, 'value'):  # It's an enum
            data[key] = value.value
    return data


def create_storage_backend(backend_name: str, **kwargs) -> StorageBackend:
    backend_class = STORAGE_BACKENDS[backend_name]
    logger.debug(f"Creating storage backend type '{backend_name}' with implementation '{backend_class}'")
    return import_string(backend_class)(**kwargs)


class Storage:
    def __init__(self, backend: StorageBackend = MemoryBackend(), ttl=None):
        self.backend = backend
        self.prefix = "deriva-groups:"
        self.groups_prefix = "groups:"
        self.memberships_prefix = "memberships:"
        self.invitations_prefix = "invitations:"
        self.user_groups_prefix = "user_groups:"
        self.group_members_prefix = "group_members:"
        self.invitation_tokens_prefix = "invitation_tokens:"
        self.join_requests_prefix = "join_requests:"
        self.join_request_tokens_prefix = "join_request_tokens:"
        self.group_join_requests_prefix = "group_join_requests:"
        self.user_join_requests_prefix = "user_join_requests:"
        self.session_cache_prefix = "session_cache:"

    def _key(self, prefix, identifier):
        return f"{self.prefix}{prefix}{identifier}"

    # Group management
    def create_group(self, group: Group) -> None:
        """Create a new group"""
        group_key = self._key(self.groups_prefix, group.id)
        # Use asdict() for storage to preserve original data types (floats for timestamps)
        group_data = json.dumps(_prepare_for_json(group))
        self.backend.set(group_key, group_data)  # Persistent storage, no TTL
        logger.debug(f"Created group {group.id}: {group.name}")

    def get_group(self, group_id: str) -> Optional[Group]:
        """Get a group by ID"""
        group_key = self._key(self.groups_prefix, group_id)
        data = self.backend.get(group_key)
        if not data:
            return None
        try:
            group_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
            return Group.from_dict(group_dict)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse group data for {group_id}: {e}")
            return None

    def update_group(self, group: Group) -> None:
        """Update an existing group"""
        group.updated_at = time.time()
        group_key = self._key(self.groups_prefix, group.id)
        # Use asdict() for storage to preserve original data types (floats for timestamps)
        group_data = json.dumps(_prepare_for_json(group))
        self.backend.set(group_key, group_data)  # Persistent storage, no TTL
        logger.debug(f"Updated group {group.id}")

    def delete_group(self, group_id: str) -> None:
        """Delete a group and all associated memberships and invitations"""
        # Delete the group
        group_key = self._key(self.groups_prefix, group_id)
        self.backend.delete(group_key)

        # Delete all memberships for this group
        memberships = self.get_group_memberships(group_id)
        for membership in memberships:
            self.remove_membership(group_id, membership.user_id)

        # Delete all invitations for this group
        invitations = self.get_group_invitations(group_id)
        for invitation in invitations:
            self.delete_invitation(invitation.id)

        logger.debug(f"Deleted group {group_id}")

    def list_groups(self) -> List[Group]:
        """List all groups"""
        pattern = self._key(self.groups_prefix, "*")
        groups = []
        for key in self.backend.scan_iter(pattern):
            data = self.backend.get(key)
            if data:
                try:
                    group_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
                    groups.append(Group.from_dict(group_dict))
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to parse group data for key {key}: {e}")
        return groups

    # Membership management
    def add_membership(self, membership: GroupMembership) -> None:
        """Add a user to a group with a specific role"""
        # Store membership
        membership_key = self._key(self.memberships_prefix, f"{membership.group_id}:{membership.user_id}")
        membership_data = json.dumps(_prepare_for_json(membership))
        self.backend.set(membership_key, membership_data)  # Persistent storage, no TTL

        # Update user's groups index
        user_groups_key = self._key(self.user_groups_prefix, membership.user_id)
        user_groups = self._get_string_set(user_groups_key)
        user_groups.add(membership.group_id)
        self._set_string_set(user_groups_key, user_groups)

        # Update group members index
        group_members_key = self._key(self.group_members_prefix, membership.group_id)
        group_members = self._get_string_set(group_members_key)
        group_members.add(membership.user_id)
        self._set_string_set(group_members_key, group_members)

        logger.debug(
            f"Added user {membership.user_id} to group {membership.group_id} with role {membership.role.value}")

    def get_membership(self, group_id: str, user_id: str) -> Optional[GroupMembership]:
        """Get a specific group membership"""
        membership_key = self._key(self.memberships_prefix, f"{group_id}:{user_id}")
        data = self.backend.get(membership_key)
        if not data:
            return None
        try:
            membership_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
            return GroupMembership.from_dict(membership_dict)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse membership data for {group_id}:{user_id}: {e}")
            return None

    def update_membership(self, membership: GroupMembership) -> None:
        """Update an existing membership"""
        membership.updated_at = time.time()
        membership_key = self._key(self.memberships_prefix, f"{membership.group_id}:{membership.user_id}")
        membership_data = json.dumps(_prepare_for_json(membership))
        self.backend.set(membership_key, membership_data)  # Persistent storage, no TTL
        logger.debug(f"Updated membership for user {membership.user_id} in group {membership.group_id}")

    def remove_membership(self, group_id: str, user_id: str) -> None:
        """Remove a user from a group"""
        # Remove membership
        membership_key = self._key(self.memberships_prefix, f"{group_id}:{user_id}")
        self.backend.delete(membership_key)

        # Update user's groups index
        user_groups_key = self._key(self.user_groups_prefix, user_id)
        user_groups = self._get_string_set(user_groups_key)
        user_groups.discard(group_id)
        self._set_string_set(user_groups_key, user_groups)

        # Update group members index
        group_members_key = self._key(self.group_members_prefix, group_id)
        group_members = self._get_string_set(group_members_key)
        group_members.discard(user_id)
        self._set_string_set(group_members_key, group_members)

        logger.debug(f"Removed user {user_id} from group {group_id}")

    def get_user_memberships(self, user_id: str) -> List[GroupMembership]:
        """Get all group memberships for a user"""
        user_groups_key = self._key(self.user_groups_prefix, user_id)
        group_ids = self._get_string_set(user_groups_key)

        memberships = []
        for group_id in group_ids:
            membership = self.get_membership(group_id, user_id)
            if membership:
                memberships.append(membership)
        return memberships

    def get_group_memberships(self, group_id: str) -> List[GroupMembership]:
        """Get all memberships for a group"""
        group_members_key = self._key(self.group_members_prefix, group_id)
        user_ids = self._get_string_set(group_members_key)

        memberships = []
        for user_id in user_ids:
            membership = self.get_membership(group_id, user_id)
            if membership:
                memberships.append(membership)
        return memberships

    # Invitation management
    def create_invitation(self, invitation: GroupInvitation) -> None:
        """Create a new group invitation"""
        invitation_key = self._key(self.invitations_prefix, invitation.id)
        invitation_data = json.dumps(_prepare_for_json(invitation))

        # Store invitation with expiry
        ttl = int(invitation.expires_at - time.time())
        if ttl > 0:
            self.backend.setex(invitation_key, invitation_data, ttl)

            # Create token mapping for easy lookup
            token_key = self._key(self.invitation_tokens_prefix, invitation.token)
            self.backend.setex(token_key, invitation.id, ttl)

            logger.debug(f"Created invitation {invitation.id} for {invitation.email} to group {invitation.group_id}")

    def get_invitation(self, invitation_id: str) -> Optional[GroupInvitation]:
        """Get an invitation by ID"""
        invitation_key = self._key(self.invitations_prefix, invitation_id)
        data = self.backend.get(invitation_key)
        if not data:
            return None
        try:
            invitation_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
            return GroupInvitation.from_dict(invitation_dict)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse invitation data for {invitation_id}: {e}")
            return None

    def get_invitation_by_token(self, token: str) -> Optional[GroupInvitation]:
        """Get an invitation by token"""
        token_key = self._key(self.invitation_tokens_prefix, token)
        invitation_id = self.backend.get(token_key)
        if not invitation_id:
            return None
        invitation_id = invitation_id.decode() if isinstance(invitation_id, bytes) else invitation_id
        return self.get_invitation(invitation_id)

    def update_invitation(self, invitation: GroupInvitation) -> None:
        """Update an existing invitation"""
        invitation_key = self._key(self.invitations_prefix, invitation.id)
        invitation_data = json.dumps(_prepare_for_json(invitation))

        # Calculate remaining TTL
        ttl = int(invitation.expires_at - time.time())
        if ttl > 0:
            self.backend.setex(invitation_key, invitation_data, ttl)
            logger.debug(f"Updated invitation {invitation.id}")
        else:
            # Invitation has expired, mark as expired
            invitation.status = InvitationStatus.EXPIRED
            self.backend.setex(invitation_key, json.dumps(invitation.to_dict()), 86400)  # Keep for 1 day
            logger.debug(f"Marked invitation {invitation.id} as expired")

    def delete_invitation(self, invitation_id: str) -> None:
        """Delete an invitation"""
        invitation = self.get_invitation(invitation_id)
        if invitation:
            # Delete token mapping
            token_key = self._key(self.invitation_tokens_prefix, invitation.token)
            self.backend.delete(token_key)

        # Delete invitation
        invitation_key = self._key(self.invitations_prefix, invitation_id)
        self.backend.delete(invitation_key)
        logger.debug(f"Deleted invitation {invitation_id}")

    def get_group_invitations(self, group_id: str) -> List[GroupInvitation]:
        """Get all invitations for a group"""
        pattern = self._key(self.invitations_prefix, "*")
        invitations = []
        for key in self.backend.scan_iter(pattern):
            data = self.backend.get(key)
            if data:
                try:
                    invitation_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
                    invitation = GroupInvitation.from_dict(invitation_dict)
                    if invitation.group_id == group_id:
                        invitations.append(invitation)
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to parse invitation data for key {key}: {e}")
        return invitations

    def get_user_invitations(self, email: str) -> List[GroupInvitation]:
        """Get all pending invitations for a user by email"""
        pattern = self._key(self.invitations_prefix, "*")
        invitations = []
        for key in self.backend.scan_iter(pattern):
            data = self.backend.get(key)
            if data:
                try:
                    invitation_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
                    invitation = GroupInvitation.from_dict(invitation_dict)
                    if invitation.email.lower() == email.lower() and invitation.is_valid():
                        invitations.append(invitation)
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to parse invitation data for key {key}: {e}")
        return invitations

    # Join Request management
    def create_join_request(self, join_request: JoinRequest) -> None:
        """Create a new join request"""
        join_request_key = self._key(self.join_requests_prefix, join_request.id)
        join_request_data = json.dumps(_prepare_for_json(join_request))

        # Store join request persistently
        self.backend.set(join_request_key, join_request_data)

        # Create token mapping with TTL for access control
        token_key = self._key(self.join_request_tokens_prefix, join_request.token)
        ttl = int(join_request.expires_at - time.time())
        if ttl > 0:
            self.backend.setex(token_key, join_request.id, ttl)

        # Update group index
        group_requests_key = self._key(self.group_join_requests_prefix, join_request.group_id)
        group_requests = self._get_string_set(group_requests_key)
        group_requests.add(join_request.id)
        self._set_string_set(group_requests_key, group_requests)

        # Update user index
        user_requests_key = self._key(self.user_join_requests_prefix, join_request.user_id)
        user_requests = self._get_string_set(user_requests_key)
        user_requests.add(join_request.id)
        self._set_string_set(user_requests_key, user_requests)

        logger.debug(
            f"Created join request {join_request.id} for user {join_request.user_email} to group {join_request.group_id}")

    def get_join_request(self, request_id: str) -> Optional[JoinRequest]:
        """Get a join request by ID"""
        request_key = self._key(self.join_requests_prefix, request_id)
        data = self.backend.get(request_key)
        if not data:
            return None
        try:
            request_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
            return JoinRequest.from_dict(request_dict)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse join request data for {request_id}: {e}")
            return None

    def get_join_request_by_token(self, token: str) -> Optional[JoinRequest]:
        """Get a join request by token"""
        token_key = self._key(self.join_request_tokens_prefix, token)
        request_id = self.backend.get(token_key)
        if not request_id:
            return None
        request_id = request_id.decode() if isinstance(request_id, bytes) else request_id
        return self.get_join_request(request_id)

    def update_join_request(self, join_request: JoinRequest) -> None:
        """Update an existing join request"""
        request_key = self._key(self.join_requests_prefix, join_request.id)
        request_data = json.dumps(_prepare_for_json(join_request))

        # Store join request persistently
        self.backend.set(request_key, request_data)
        logger.debug(f"Updated join request {join_request.id}")

    def delete_join_request(self, request_id: str) -> None:
        """Delete a join request"""
        join_request = self.get_join_request(request_id)
        if join_request:
            # Delete token mapping
            token_key = self._key(self.join_request_tokens_prefix, join_request.token)
            self.backend.delete(token_key)

            # Update group index
            group_requests_key = self._key(self.group_join_requests_prefix, join_request.group_id)
            group_requests = self._get_string_set(group_requests_key)
            group_requests.discard(request_id)
            self._set_string_set(group_requests_key, group_requests)

            # Update user index
            user_requests_key = self._key(self.user_join_requests_prefix, join_request.user_id)
            user_requests = self._get_string_set(user_requests_key)
            user_requests.discard(request_id)
            self._set_string_set(user_requests_key, user_requests)

        # Delete join request
        request_key = self._key(self.join_requests_prefix, request_id)
        self.backend.delete(request_key)
        logger.debug(f"Deleted join request {request_id}")

    def get_group_join_requests(self, group_id: str) -> List[JoinRequest]:
        """Get all join requests for a group"""
        group_requests_key = self._key(self.group_join_requests_prefix, group_id)
        request_ids = self._get_string_set(group_requests_key)

        requests = []
        for request_id in request_ids:
            join_request = self.get_join_request(request_id)
            if join_request:
                requests.append(join_request)
        return requests

    def get_user_join_requests(self, user_id: str) -> List[JoinRequest]:
        """Get all join requests for a user"""
        user_requests_key = self._key(self.user_join_requests_prefix, user_id)
        request_ids = self._get_string_set(user_requests_key)

        requests = []
        for request_id in request_ids:
            join_request = self.get_join_request(request_id)
            if join_request:
                requests.append(join_request)
        return requests

    def get_pending_join_requests_for_group(self, group_id: str) -> List[JoinRequest]:
        """Get pending join requests for a group"""
        all_requests = self.get_group_join_requests(group_id)
        return [req for req in all_requests if req.is_pending()]

    def has_pending_join_request(self, group_id: str, user_id: str) -> bool:
        """Check if user has a pending join request for a group"""
        user_requests = self.get_user_join_requests(user_id)
        for request in user_requests:
            if request.group_id == group_id and request.is_pending():
                return True
        return False

    def cleanup_expired_requests(self) -> int:
        """Clean up expired join requests and return count"""
        pattern = self._key(self.join_requests_prefix, "*")
        cleaned_count = 0

        for key in self.backend.scan_iter(pattern):
            data = self.backend.get(key)
            if data:
                try:
                    request_dict = json.loads(data.decode() if isinstance(data, bytes) else data)
                    join_request = JoinRequest.from_dict(request_dict)
                    if join_request.is_expired() and join_request.status == JoinRequestStatus.PENDING:
                        join_request.status = JoinRequestStatus.EXPIRED
                        self.update_join_request(join_request)
                        cleaned_count += 1
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to parse join request data for cleanup: {e}")

        logger.info(f"Cleaned up {cleaned_count} expired join requests")
        return cleaned_count

    def get_session(self, session_key: str) -> Optional[dict]:
        session = self.backend.get(self._key(self.session_cache_prefix, session_key))
        if session:
            return json.loads(session.decode())
        else:
            return None

    def set_session(self, session_key: str, session_data: dict, ttl: Optional[int] = 1800) -> None:
        return self.backend.setex(self._key(self.session_cache_prefix, session_key), json.dumps(session_data), ttl)

    def delete_session(self, session_key: str) -> None:
        return self.backend.delete(self._key(self.session_cache_prefix, session_key))

    # Helper methods for set operations
    def _get_string_set(self, key: str) -> set:
        data = self.backend.get(key)
        if not data:
            return set()
        try:
            return set(json.loads(data.decode() if isinstance(data, bytes) else data))
        except (ValueError, json.JSONDecodeError):
            return set()

    def _set_string_set(self, key: str, string_set: set) -> None:
        data = json.dumps(list(string_set))
        self.backend.set(key, data)  # Persistent storage, no TTL
