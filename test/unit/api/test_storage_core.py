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

import pytest
import time
import uuid
import redis
import fakeredis
import testing.postgresql
from deriva.web.groups.api.storage.core import Storage, create_storage_backend
from deriva.web.groups.api.storage.backends.memory import MemoryBackend
from deriva.web.groups.api.storage.backends.redis import RedisBackend
from deriva.web.groups.api.storage.backends.sqlite import SQLiteBackend
from deriva.web.groups.api.storage.backends.postgresql import PostgreSQLBackend
from deriva.web.groups.api.groups.models import (
    Group, GroupMembership, GroupInvitation, JoinRequest,
    GroupRole, InvitationStatus, JoinRequestStatus
)

class _PostgreSQLBackend(PostgreSQLBackend):

    def __init__(self):
        _postgresql = testing.postgresql.Postgresql()
        super(_PostgreSQLBackend, self).__init__(url=_postgresql.url())
        # save a reference to our test DB so it isn't reaped before us
        self._testing_postgresql = _postgresql

    def close(self):
        self._testing_postgresql.stop()
        del self._testing_postgresql
        super(_PostgreSQLBackend, self).close()

class TestCreateStorageBackend:
    """Test storage backend creation"""
    
    def test_create_memory_backend(self):
        """Test creating memory backend"""
        backend = create_storage_backend("memory")
        assert isinstance(backend, MemoryBackend)
    
    def test_create_backend_with_invalid_name(self):
        """Test creating backend with invalid name"""
        with pytest.raises(KeyError):
            create_storage_backend("invalid_backend")

@pytest.fixture(params=[
    "redis",
    "sqlite",
    "postgresql",
    "memory"],
    ids=lambda val: val, scope="function")
def storage(request, monkeypatch):

    backend_type = request.param
    server = fakeredis.FakeServer()
    fake_redis = fakeredis.FakeRedis(server=server)

    if backend_type.startswith("redis"):
        monkeypatch.setattr(
            redis.Redis, "from_url",
            classmethod(lambda cls, url: fake_redis)
        )
        backend = RedisBackend(url="redis://fake")
    elif backend_type.startswith("sqlite"):
        backend = SQLiteBackend()
    elif backend_type.startswith("postgresql"):
        backend = _PostgreSQLBackend()
    elif backend_type.startswith("memory"):
        backend = MemoryBackend()
    else:
        raise RuntimeError(f"Unknown backend {backend_type}")

    return Storage(backend)

class TestStorageGroupOperations:
    """Test Storage group operations"""
    
    def test_create_group(self, storage, sample_group):
        """Test creating a group"""
        storage.create_group(sample_group)
        
        # Verify group was created
        retrieved_group = storage.get_group(sample_group.id)
        assert retrieved_group is not None
        assert retrieved_group.id == sample_group.id
        assert retrieved_group.name == sample_group.name
        assert retrieved_group.description == sample_group.description
        assert retrieved_group.visibility == sample_group.visibility
        assert retrieved_group.created_by == sample_group.created_by
        assert retrieved_group.metadata == sample_group.metadata
    
    def test_get_nonexistent_group(self, storage):
        """Test getting non-existent group"""
        result = storage.get_group("nonexistent_id")
        assert result is None
    
    def test_update_group(self, storage, sample_group, mock_time):
        """Test updating a group"""
        # Create initial group
        storage.create_group(sample_group)
        original_updated_at = sample_group.updated_at
        
        # Update group (mock_time ensures different timestamp)
        sample_group.name = "Updated Group"
        sample_group.description = "Updated description"
        sample_group.visibility = "public"
        sample_group.metadata = {"new": "metadata"}
        
        storage.update_group(sample_group)
        
        # Verify updates
        retrieved_group = storage.get_group(sample_group.id)
        assert retrieved_group.name == "Updated Group"
        assert retrieved_group.description == "Updated description"
        assert retrieved_group.visibility == "public"
        assert retrieved_group.metadata == {"new": "metadata"}
        # Check that updated_at was changed from the original
        assert retrieved_group.updated_at != original_updated_at
    
    def test_delete_group(self, storage, sample_group):
        """Test deleting a group"""
        # Create group
        storage.create_group(sample_group)
        
        # Add membership
        membership = GroupMembership(
            group_id=sample_group.id,
            user_id="user123",
            user_email="user@example.com",
            role=GroupRole.MEMBER
        )
        storage.add_membership(membership)
        
        # Add invitation
        invitation = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            email="invitee@example.com",
            role=GroupRole.MEMBER,
            token=str(uuid.uuid4().hex)
        )
        storage.create_invitation(invitation)
        
        # Delete group
        storage.delete_group(sample_group.id)
        
        # Verify group is deleted
        assert storage.get_group(sample_group.id) is None
        # Verify membership is deleted
        assert storage.get_membership(sample_group.id, "user123") is None
        # Verify invitation is deleted
        assert storage.get_invitation(invitation.id) is None
    
    def test_list_groups(self, storage):
        """Test listing groups"""
        # Create multiple groups
        group1 = Group(id=str(uuid.uuid4()), name="Group 1")
        group2 = Group(id=str(uuid.uuid4()), name="Group 2")
        group3 = Group(id=str(uuid.uuid4()), name="Group 3")
        
        storage.create_group(group1)
        storage.create_group(group2)
        storage.create_group(group3)
        
        # List groups
        groups = storage.list_groups()
        
        assert len(groups) == 3
        group_names = [g.name for g in groups]
        assert "Group 1" in group_names
        assert "Group 2" in group_names
        assert "Group 3" in group_names
    
    def test_list_empty_groups(self, storage):
        """Test listing when no groups exist"""
        groups = storage.list_groups()
        assert groups == []


class TestStorageMembershipOperations:
    """Test Storage membership operations"""
    
    def test_add_membership(self, storage, sample_group, sample_membership):
        """Test adding membership"""
        # Create group first
        storage.create_group(sample_group)
        
        # Add membership
        storage.add_membership(sample_membership)
        
        # Verify membership was added
        retrieved_membership = storage.get_membership(
            sample_membership.group_id, sample_membership.user_id
        )
        assert retrieved_membership is not None
        assert retrieved_membership.group_id == sample_membership.group_id
        assert retrieved_membership.user_id == sample_membership.user_id
        assert retrieved_membership.user_email == sample_membership.user_email
        assert retrieved_membership.role == sample_membership.role
        assert retrieved_membership.added_by == sample_membership.added_by
    
    def test_get_nonexistent_membership(self, storage):
        """Test getting non-existent membership"""
        result = storage.get_membership("nonexistent_group", "nonexistent_user")
        assert result is None
    
    def test_update_membership(self, storage, sample_group, sample_membership, mock_time):
        """Test updating membership"""
        # Create group and membership
        storage.create_group(sample_group)
        storage.add_membership(sample_membership)
        original_updated_at = sample_membership.updated_at
        
        # Update membership (mock_time ensures different timestamp)
        sample_membership.role = GroupRole.ADMINISTRATOR
        sample_membership.metadata = {"promotion": "earned"}
        
        storage.update_membership(sample_membership)
        
        # Verify updates
        retrieved_membership = storage.get_membership(
            sample_membership.group_id, sample_membership.user_id
        )
        assert retrieved_membership.role == GroupRole.ADMINISTRATOR
        assert retrieved_membership.metadata == {"promotion": "earned"}
        # Check that updated_at was changed from the original
        assert retrieved_membership.updated_at != original_updated_at
    
    def test_remove_membership(self, storage, sample_group, sample_membership):
        """Test removing membership"""
        # Create group and membership
        storage.create_group(sample_group)
        storage.add_membership(sample_membership)
        
        # Remove membership
        storage.remove_membership(sample_membership.group_id, sample_membership.user_id)
        
        # Verify membership is removed
        result = storage.get_membership(
            sample_membership.group_id, sample_membership.user_id
        )
        assert result is None
    
    def test_get_user_memberships(self, storage):
        """Test getting user memberships"""
        # Create groups
        group1 = Group(id=str(uuid.uuid4()), name="Group 1")
        group2 = Group(id=str(uuid.uuid4()), name="Group 2")
        storage.create_group(group1)
        storage.create_group(group2)
        
        # Add memberships
        membership1 = GroupMembership(
            group_id=group1.id,
            user_id="user123",
            user_email="user@example.com",
            role=GroupRole.MEMBER
        )
        membership2 = GroupMembership(
            group_id=group2.id,
            user_id="user123",
            user_email="user@example.com",
            role=GroupRole.ADMINISTRATOR
        )
        
        storage.add_membership(membership1)
        storage.add_membership(membership2)
        
        # Get user memberships
        memberships = storage.get_user_memberships("user123")
        
        assert len(memberships) == 2
        group_ids = [m.group_id for m in memberships]
        assert group1.id in group_ids
        assert group2.id in group_ids
    
    def test_get_group_memberships(self, storage, sample_group):
        """Test getting group memberships"""
        # Create group
        storage.create_group(sample_group)
        
        # Add multiple memberships
        membership1 = GroupMembership(
            group_id=sample_group.id,
            user_id="user1",
            user_email="user1@example.com",
            role=GroupRole.ADMINISTRATOR
        )
        membership2 = GroupMembership(
            group_id=sample_group.id,
            user_id="user2",
            user_email="user2@example.com",
            role=GroupRole.MEMBER
        )
        
        storage.add_membership(membership1)
        storage.add_membership(membership2)
        
        # Get group memberships
        memberships = storage.get_group_memberships(sample_group.id)
        
        assert len(memberships) == 2
        user_ids = [m.user_id for m in memberships]
        assert "user1" in user_ids
        assert "user2" in user_ids


class TestStorageInvitationOperations:
    """Test Storage invitation operations"""
    
    def test_create_invitation(self, storage, sample_invitation):
        """Test creating invitation"""
        storage.create_invitation(sample_invitation)
        
        # Verify invitation was created
        retrieved_invitation = storage.get_invitation(sample_invitation.id)
        assert retrieved_invitation is not None
        assert retrieved_invitation.id == sample_invitation.id
        assert retrieved_invitation.group_id == sample_invitation.group_id
        assert retrieved_invitation.email == sample_invitation.email
        assert retrieved_invitation.role == sample_invitation.role
        assert retrieved_invitation.token == sample_invitation.token
    
    def test_get_invitation_by_token(self, storage, sample_invitation):
        """Test getting invitation by token"""
        storage.create_invitation(sample_invitation)
        
        # Get by token
        retrieved_invitation = storage.get_invitation_by_token(sample_invitation.token)
        assert retrieved_invitation is not None
        assert retrieved_invitation.id == sample_invitation.id
        assert retrieved_invitation.token == sample_invitation.token
    
    def test_get_nonexistent_invitation(self, storage):
        """Test getting non-existent invitation"""
        result = storage.get_invitation("nonexistent_id")
        assert result is None
    
    def test_get_invitation_by_nonexistent_token(self, storage):
        """Test getting invitation by non-existent token"""
        result = storage.get_invitation_by_token("nonexistent_token")
        assert result is None
    
    def test_update_invitation(self, storage, sample_invitation):
        """Test updating invitation"""
        # Create invitation
        storage.create_invitation(sample_invitation)
        
        # Update invitation
        sample_invitation.status = InvitationStatus.ACCEPTED
        sample_invitation.accepted_by = "user123"
        sample_invitation.accepted_at = time.time()
        
        storage.update_invitation(sample_invitation)
        
        # Verify updates
        retrieved_invitation = storage.get_invitation(sample_invitation.id)
        assert retrieved_invitation.status == InvitationStatus.ACCEPTED
        assert retrieved_invitation.accepted_by == "user123"
        assert retrieved_invitation.accepted_at == sample_invitation.accepted_at
    
    def test_delete_invitation(self, storage, sample_invitation):
        """Test deleting invitation"""
        # Create invitation
        storage.create_invitation(sample_invitation)
        
        # Delete invitation
        storage.delete_invitation(sample_invitation.id)
        
        # Verify invitation is deleted
        assert storage.get_invitation(sample_invitation.id) is None
        assert storage.get_invitation_by_token(sample_invitation.token) is None
    
    def test_get_group_invitations(self, storage, sample_group):
        """Test getting group invitations"""
        # Create multiple invitations for the group
        invitation1 = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            email="user1@example.com",
            role=GroupRole.MEMBER,
            token=str(uuid.uuid4().hex)
        )
        invitation2 = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            email="user2@example.com",
            role=GroupRole.ADMINISTRATOR,
            token=str(uuid.uuid4().hex)
        )
        
        storage.create_invitation(invitation1)
        storage.create_invitation(invitation2)
        
        # Get group invitations
        invitations = storage.get_group_invitations(sample_group.id)
        
        assert len(invitations) == 2
        emails = [inv.email for inv in invitations]
        assert "user1@example.com" in emails
        assert "user2@example.com" in emails
    
    def test_get_user_invitations(self, storage):
        """Test getting user invitations"""
        # Create groups
        group1 = Group(id=str(uuid.uuid4()), name="Group 1")
        group2 = Group(id=str(uuid.uuid4()), name="Group 2")
        
        # Create invitations
        invitation1 = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=group1.id,
            group_name=group1.name,
            email="user@example.com",
            role=GroupRole.MEMBER,
            token=str(uuid.uuid4().hex),
            status=InvitationStatus.PENDING
        )
        invitation2 = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=group2.id,
            group_name=group2.name,
            email="user@example.com",
            role=GroupRole.ADMINISTRATOR,
            token=str(uuid.uuid4().hex),
            status=InvitationStatus.PENDING
        )
        invitation3 = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=group1.id,
            group_name=group1.name,
            email="user@example.com",
            role=GroupRole.MEMBER,
            token=str(uuid.uuid4().hex),
            status=InvitationStatus.ACCEPTED  # Not valid
        )
        
        storage.create_invitation(invitation1)
        storage.create_invitation(invitation2)
        storage.create_invitation(invitation3)
        
        # Get user invitations (only valid ones)
        invitations = storage.get_user_invitations("user@example.com")
        
        assert len(invitations) == 2  # Only pending ones
        statuses = [inv.status for inv in invitations]
        assert all(status == InvitationStatus.PENDING for status in statuses)


class TestStorageJoinRequestOperations:
    """Test Storage join request operations"""
    
    def test_create_join_request(self, storage, sample_join_request):
        """Test creating join request"""
        storage.create_join_request(sample_join_request)
        
        # Verify join request was created
        retrieved_request = storage.get_join_request(sample_join_request.id)
        assert retrieved_request is not None
        assert retrieved_request.id == sample_join_request.id
        assert retrieved_request.group_id == sample_join_request.group_id
        assert retrieved_request.user_id == sample_join_request.user_id
        assert retrieved_request.user_email == sample_join_request.user_email
        assert retrieved_request.message == sample_join_request.message
    
    def test_get_join_request_by_token(self, storage, sample_join_request):
        """Test getting join request by token"""
        storage.create_join_request(sample_join_request)
        
        # Get by token
        retrieved_request = storage.get_join_request_by_token(sample_join_request.token)
        assert retrieved_request is not None
        assert retrieved_request.id == sample_join_request.id
        assert retrieved_request.token == sample_join_request.token
    
    def test_update_join_request(self, storage, sample_join_request):
        """Test updating join request"""
        # Create join request
        storage.create_join_request(sample_join_request)
        
        # Update join request
        sample_join_request.status = JoinRequestStatus.APPROVED
        sample_join_request.reviewed_by = "admin123"
        sample_join_request.reviewed_at = time.time()
        sample_join_request.reviewer_comment = "Welcome!"
        
        storage.update_join_request(sample_join_request)
        
        # Verify updates
        retrieved_request = storage.get_join_request(sample_join_request.id)
        assert retrieved_request.status == JoinRequestStatus.APPROVED
        assert retrieved_request.reviewed_by == "admin123"
        assert retrieved_request.reviewed_at == sample_join_request.reviewed_at
        assert retrieved_request.reviewer_comment == "Welcome!"
    
    def test_delete_join_request(self, storage, sample_join_request):
        """Test deleting join request"""
        # Create join request
        storage.create_join_request(sample_join_request)
        
        # Delete join request
        storage.delete_join_request(sample_join_request.id)
        
        # Verify join request is deleted
        assert storage.get_join_request(sample_join_request.id) is None
        assert storage.get_join_request_by_token(sample_join_request.token) is None
    
    def test_get_group_join_requests(self, storage, sample_group):
        """Test getting group join requests"""
        # Create multiple join requests for the group
        request1 = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user1",
            user_email="user1@example.com",
            user_name="User 1",
            token=str(uuid.uuid4().hex)
        )
        request2 = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user2",
            user_email="user2@example.com",
            user_name="User 2",
            token=str(uuid.uuid4().hex)
        )
        
        storage.create_join_request(request1)
        storage.create_join_request(request2)
        
        # Get group join requests
        requests = storage.get_group_join_requests(sample_group.id)
        
        assert len(requests) == 2
        user_ids = [req.user_id for req in requests]
        assert "user1" in user_ids
        assert "user2" in user_ids
    
    def test_get_user_join_requests(self, storage):
        """Test getting user join requests"""
        # Create groups
        group1 = Group(id=str(uuid.uuid4()), name="Group 1")
        group2 = Group(id=str(uuid.uuid4()), name="Group 2")
        
        # Create join requests
        request1 = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group1.id,
            group_name=group1.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            token=str(uuid.uuid4().hex)
        )
        request2 = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group2.id,
            group_name=group2.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            token=str(uuid.uuid4().hex)
        )
        
        storage.create_join_request(request1)
        storage.create_join_request(request2)
        
        # Get user join requests
        requests = storage.get_user_join_requests("user123")
        
        assert len(requests) == 2
        group_ids = [req.group_id for req in requests]
        assert group1.id in group_ids
        assert group2.id in group_ids
    
    def test_get_pending_join_requests_for_group(self, storage, sample_group):
        """Test getting pending join requests for group"""
        # Create join requests with different statuses
        pending_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user1",
            user_email="user1@example.com",
            user_name="User 1",
            status=JoinRequestStatus.PENDING,
            token=str(uuid.uuid4().hex)
        )
        approved_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user2",
            user_email="user2@example.com",
            user_name="User 2",
            status=JoinRequestStatus.APPROVED,
            token=str(uuid.uuid4().hex)
        )
        
        storage.create_join_request(pending_request)
        storage.create_join_request(approved_request)
        
        # Get pending requests only
        requests = storage.get_pending_join_requests_for_group(sample_group.id)
        
        assert len(requests) == 1
        assert requests[0].id == pending_request.id
        assert requests[0].status == JoinRequestStatus.PENDING
    
    def test_has_pending_join_request(self, storage, sample_group):
        """Test checking for pending join request"""
        # Create pending join request
        pending_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            status=JoinRequestStatus.PENDING,
            token=str(uuid.uuid4().hex)
        )
        
        storage.create_join_request(pending_request)
        
        # Check for pending request
        assert storage.has_pending_join_request(sample_group.id, "user123") is True
        assert storage.has_pending_join_request(sample_group.id, "other_user") is False
    
    def test_cleanup_expired_requests(self, storage, sample_group):
        """Test cleaning up expired join requests"""
        # Create expired pending request
        expired_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            status=JoinRequestStatus.PENDING,
            expires_at=time.time() - 3600,  # 1 hour ago
            token=str(uuid.uuid4().hex)
        )
        
        # Create valid pending request
        valid_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=sample_group.id,
            group_name=sample_group.name,
            user_id="user456",
            user_email="user2@example.com",
            user_name="Test User 2",
            status=JoinRequestStatus.PENDING,
            expires_at=time.time() + 3600,  # 1 hour from now
            token=str(uuid.uuid4().hex)
        )
        
        storage.create_join_request(expired_request)
        storage.create_join_request(valid_request)
        
        # Cleanup expired requests
        cleaned_count = storage.cleanup_expired_requests()
        
        assert cleaned_count == 1
        
        # Verify expired request status was updated
        updated_request = storage.get_join_request(expired_request.id)
        assert updated_request.status == JoinRequestStatus.EXPIRED
        
        # Verify valid request is unchanged
        valid_request_check = storage.get_join_request(valid_request.id)
        assert valid_request_check.status == JoinRequestStatus.PENDING


class TestStorageSessionOperations:
    """Test Storage session operations"""
    
    def test_set_and_get_session(self, storage):
        """Test setting and getting session"""
        session_data = {
            "user_id": "user123",
            "email": "user@example.com",
            "name": "Test User"
        }
        
        storage.set_session("session_key", session_data, 3600)
        
        retrieved_session = storage.get_session("session_key")
        assert retrieved_session == session_data
    
    def test_get_nonexistent_session(self, storage):
        """Test getting non-existent session"""
        result = storage.get_session("nonexistent_key")
        assert result is None
    
    def test_delete_session(self, storage):
        """Test deleting session"""
        session_data = {"user_id": "user123"}
        
        storage.set_session("session_key", session_data, 3600)
        storage.delete_session("session_key")
        
        result = storage.get_session("session_key")
        assert result is None


class TestStorageHelperMethods:
    """Test Storage helper methods"""
    
    def test_get_string_set_empty(self, storage):
        """Test getting empty string set"""
        result = storage._get_string_set("nonexistent_key")
        assert result == set()
    
    def test_set_and_get_string_set(self, storage):
        """Test setting and getting string set"""
        test_set = {"item1", "item2", "item3"}
        
        storage._set_string_set("test_key", test_set)
        retrieved_set = storage._get_string_set("test_key")
        
        assert retrieved_set == test_set
    
    def test_modify_string_set(self, storage):
        """Test modifying string set"""
        initial_set = {"item1", "item2"}
        
        storage._set_string_set("test_key", initial_set)
        
        # Modify set
        modified_set = storage._get_string_set("test_key")
        modified_set.add("item3")
        modified_set.remove("item1")
        
        storage._set_string_set("test_key", modified_set)
        
        final_set = storage._get_string_set("test_key")
        assert final_set == {"item2", "item3"}
