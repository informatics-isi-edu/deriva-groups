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
import pytest
from unittest.mock import Mock, patch
from flask import Flask, g
from deriva.web.groups.rest.groups import groups_blueprint
from deriva.web.groups.api.groups.models import Group, GroupMembership, GroupRole, GroupInvitation, InvitationStatus


@pytest.fixture
def app():
    """Create Flask app for testing"""
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['SERVER_NAME'] = 'localhost'
    
    # Configure mock session manager to return proper user session
    mock_session_manager = Mock()
    mock_session_manager.get_user_session.return_value = {
        'sub': 'test_user_123',
        'email': 'test@example.com',
        'name': 'Test User'
    }
    app.config['GROUPS_CONFIG'] = {}
    app.config['SESSION_MANAGER'] = mock_session_manager
    app.config['GROUP_MANAGER'] = Mock()
    app.config['JOIN_REQUEST_MANAGER'] = Mock()
    app.register_blueprint(groups_blueprint)
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture
def mock_auth():
    """Mock authentication - return empty context manager"""
    return


@pytest.fixture
def sample_groups(mock_time):
    """Sample groups for testing"""
    return [
        Group(
            id="group1",
            name="Group 1",
            description="First test group",
            visibility="private",
            created_by="user1"
        ),
        Group(
            id="group2",
            name="Group 2",
            description="Second test group",
            visibility="public",
            created_by="user2"
        )
    ]


@pytest.fixture
def sample_memberships(mock_time):
    """Sample memberships for testing"""
    return [
        GroupMembership(
            group_id="group1",
            user_id="test_user_123",
            user_email="test@example.com",
            role=GroupRole.MEMBER
        ),
        GroupMembership(
            group_id="group1",
            user_id="user2",
            user_email="user2@example.com",
            role=GroupRole.ADMINISTRATOR
        )
    ]


@pytest.fixture
def sample_invitations(mock_time):
    """Sample invitations for testing"""
    return [
        GroupInvitation(
            id="inv1",
            group_id="group1",
            group_name="Group 1",
            email="invite1@example.com",
            role=GroupRole.MEMBER,
            invited_by="test_user_123",
            status=InvitationStatus.PENDING,
            token="token1"
        ),
        GroupInvitation(
            id="inv2",
            group_id="group1",
            group_name="Group 1",
            email="invite2@example.com",
            role=GroupRole.ADMINISTRATOR,
            invited_by="test_user_123",
            status=InvitationStatus.PENDING,
            token="token2"
        )
    ]


class TestGroupsBlueprint:
    """Test groups REST API endpoints"""

    def test_get_group_manager(self, app):
        """Test get_group_manager helper function"""
        with app.app_context():
            from deriva.web.groups.rest.groups import get_group_manager
            manager = get_group_manager()
            assert manager == app.config['GROUP_MANAGER']

    def test_get_join_request_manager(self, app):
        """Test get_join_request_manager helper function"""
        with app.app_context():
            from deriva.web.groups.rest.groups import get_join_request_manager
            manager = get_join_request_manager()
            assert manager == app.config['JOIN_REQUEST_MANAGER']

    def test_list_groups(self, app, client, mock_auth, sample_groups):
        """Test listing all groups"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.list_groups.return_value = sample_groups
        mock_group_manager.get_membership.return_value = None
        mock_group_manager.get_group_members.return_value = []
        
        response = client.get('/groups')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["groups"]) == 2
        assert data["groups"][0]['name'] == 'Group 1'
        assert data["groups"][1]['name'] == 'Group 2'
        assert 'member_count' in data["groups"][0]

    def test_list_groups_with_membership(self, app, client, mock_auth, sample_groups, sample_memberships):
        """Test listing groups when user is a member"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.list_groups.return_value = sample_groups
        mock_group_manager.get_membership.return_value = sample_memberships[0]
        mock_group_manager.get_group_members.return_value = [sample_memberships[0]]
        
        response = client.get('/groups')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        print(data)
        assert 'membership' in data["groups"][0]
        assert 'membership' in data["groups"][1]
        assert data["groups"][0]['member_count'] == 1

    def test_create_group(self, app, client, mock_auth, sample_groups, sample_memberships):
        """Test creating a new group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.can_create_group.return_value = True
        mock_group_manager.get_user_groups.return_value = [(sample_groups[0], sample_memberships[0])]

        new_group = Group(
            id="new_group_123",
            name="New Test Group",
            description="A newly created group",
            visibility="private",
            created_by="test_user_123"
        )
        mock_group_manager.create_group.return_value = new_group
        
        # Mock the add_member call that happens after group creation
        membership = GroupMembership(
            group_id="new_group_123",
            user_id="test_user_123",
            user_email="test@example.com",
            role=GroupRole.ADMINISTRATOR
        )
        mock_group_manager.add_member.return_value = membership
        
        group_data = {
            "name": "New Test Group",
            "description": "A newly created group",
            "visibility": "private",
            "metadata": {"department": "IT"}
        }
        
        response = client.post('/groups', 
                             data=json.dumps(group_data),
                             content_type='application/json')
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['name'] == 'New Test Group'
        assert data['created_by'] == 'test_user_123'
        
        # Verify the manager was called correctly
        mock_group_manager.create_group.assert_called_once_with(
            name="New Test Group",
            description="A newly created group",
            visibility="private",
            created_by="test_user_123",
            metadata={"department": "IT"}
        )

    def test_create_group_missing_name(self, app, client, mock_auth):
        """Test creating group without name"""
        group_data = {
            "description": "Group without name"
        }
        
        response = client.post('/groups',
                             data=json.dumps(group_data),
                             content_type='application/json')
        
        assert response.status_code == 400

    def test_get_group(self, app, client, mock_auth, sample_groups, sample_memberships):
        """Test getting a specific group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.get_group.return_value = sample_groups[0]
        mock_group_manager.get_membership.return_value = sample_memberships[0]  # User is a member
        mock_group_manager.user_can_manage_group.return_value = False
        
        response = client.get('/groups/group1')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == 'group1'
        assert data['name'] == 'Group 1'
        assert 'membership' in data

    def test_get_group_not_found(self, app, client, mock_auth):
        """Test getting non-existent group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.get_group.return_value = None
        
        response = client.get('/groups/nonexistent')
        
        assert response.status_code == 404

    def test_update_group(self, app, client, mock_auth, sample_groups):
        """Test updating a group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_admin_group.return_value = True
        mock_group_manager.update_group.return_value = sample_groups[0]
        
        update_data = {
            "name": "Updated Group Name",
            "description": "Updated description"
        }
        
        response = client.put('/groups/group1',
                            data=json.dumps(update_data),
                            content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['name'] == 'Group 1'  # Sample data name

    def test_update_group_insufficient_permissions(self, app, client, mock_auth):
        """Test updating group without admin permissions"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_admin_group.return_value = False
        
        update_data = {"name": "New Name"}
        
        response = client.put('/groups/group1',
                            data=json.dumps(update_data),
                            content_type='application/json')
        
        assert response.status_code == 403

    def test_delete_group(self, app, client, mock_auth):
        """Test deleting a group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_admin_group.return_value = True
        mock_group_manager.get_group.return_value = Mock(name="Test Group")
        mock_group_manager.delete_group.return_value = True
        
        response = client.delete('/groups/group1')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "deleted"
        mock_group_manager.delete_group.assert_called_once_with('group1')

    def test_delete_group_not_found(self, app, client, mock_auth):
        """Test deleting non-existent group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_admin_group.return_value = True
        mock_group_manager.get_group.return_value = None
        
        response = client.delete('/groups/nonexistent')
        
        assert response.status_code == 404

    def test_get_group_members(self, app, client, mock_auth, sample_memberships):
        """Test getting group members"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_is_member.return_value = True
        mock_group_manager.get_group_members.return_value = sample_memberships
        
        response = client.get('/groups/group1/members')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["members"]) == 2
        assert data["members"][0]['user_email'] == 'test@example.com'
        assert data["members"][1]['role'] == 'administrator'

    def test_add_group_member(self, app, client, mock_auth):
        """Test adding a member to a group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = True
        
        new_membership = GroupMembership(
            group_id="group1",
            user_id="new_user",
            user_email="new@example.com",
            role=GroupRole.MEMBER
        )
        mock_group_manager.add_member.return_value = new_membership
        
        member_data = {
            "user_id": "new_user",
            "email": "new@example.com",
            "role": "member"
        }
        
        response = client.post('/groups/group1/members',
                             data=json.dumps(member_data),
                             content_type='application/json')
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['user_id'] == 'new_user'
        assert data['role'] == 'member'

    def test_update_member_role(self, app, client, mock_auth):
        """Test updating a member's role"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = True
        mock_group_manager.get_group_members.return_value = [Mock(role=GroupRole.ADMINISTRATOR)]
        
        updated_membership = GroupMembership(
            group_id="group1",
            user_id="member_user",
            user_email="member@example.com",
            role=GroupRole.ADMINISTRATOR
        )
        mock_group_manager.update_member_role.return_value = updated_membership
        
        update_data = {
            "user_id": "member_user",
            "role": "administrator"
        }
        
        response = client.put('/groups/group1/members',
                            data=json.dumps(update_data),
                            content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['role'] == 'administrator'

    def test_remove_group_member(self, app, client, mock_auth):
        """Test removing a member from a group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = True
        mock_group_manager.get_membership.return_value = Mock(role=GroupRole.MEMBER)
        mock_group_manager.get_group_members.return_value = [Mock(role=GroupRole.ADMINISTRATOR)]
        mock_group_manager.remove_member.return_value = True
        
        remove_data = {"user_id": "member_to_remove"}
        
        response = client.delete('/groups/group1/members',
                               data=json.dumps(remove_data),
                               content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "removed"

    def test_get_group_invitations(self, app, client, mock_auth, sample_invitations):
        """Test getting group invitations"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = True
        mock_group_manager.get_group_invitations.return_value = sample_invitations
        
        response = client.get('/groups/group1/invitations')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["invitations"]) == 2
        assert data["invitations"][0]['email'] == 'invite1@example.com'
        assert data["invitations"][1]['role'] == 'administrator'

    def test_create_group_invitation(self, app, client, mock_auth):
        """Test creating a group invitation"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.get_group.return_value = Mock(name="Test Group")
        mock_group_manager.user_can_manage_group.return_value = True
        
        new_invitation = GroupInvitation(
            id="new_inv",
            group_id="group1",
            group_name="Group 1",
            email="invite@example.com",
            role=GroupRole.MEMBER,
            invited_by="test_user_123",
            status=InvitationStatus.PENDING,
            token="new_token"
        )
        mock_group_manager.create_invitation.return_value = new_invitation
        
        invitation_data = {
            "email": "invite@example.com",
            "role": "member"
        }
        
        response = client.post('/groups/group1/invitations',
                             data=json.dumps(invitation_data),
                             content_type='application/json')
        
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['email'] == 'invite@example.com'
        assert data['role'] == 'member'

    def test_revoke_invitation(self, app, client, mock_auth):
        """Test revoking an invitation"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = True
        mock_group_manager.revoke_invitation.return_value = True
        
        response = client.delete('/groups/group1/invitations/inv123')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "revoked"
        mock_group_manager.revoke_invitation.assert_called_once_with('inv123')

    def test_accept_invitation(self, app, client, mock_auth):
        """Test accepting an invitation"""
        mock_group_manager = app.config['GROUP_MANAGER']
        
        membership = GroupMembership(
            group_id="group1",
            user_id="test_user_123",
            user_email="test@example.com",
            role=GroupRole.MEMBER
        )
        mock_group_manager.accept_invitation.return_value = membership
        mock_group_manager.get_group.return_value = Mock(to_dict=Mock(return_value={"id": "group1", "name": "Test Group"}))
        
        token = "invitation_token_123"
        
        response = client.post(f'/invitations/{token}/accept',
                             content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['user_id'] == 'test_user_123'
        assert data['role'] == 'member'

    def test_accept_invitation_invalid_token(self, app, client, mock_auth):
        """Test accepting invitation with invalid token"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.accept_invitation.return_value = None
        
        invalid_token = "invalid_token"
        
        response = client.post(f'/invitations/{invalid_token}/accept',
                             content_type='application/json')
        
        assert response.status_code == 400

    def test_get_user_invitations(self, app, client, mock_auth, sample_invitations):
        """Test getting pending invitations for current user"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.get_user_invitations.return_value = sample_invitations
        mock_group_manager.get_group.return_value = Mock(to_dict=Mock(return_value={"id": "group1", "name": "Test Group"}))
        
        response = client.get('/invitations/pending')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["invitations"]) == 2
        assert data["invitations"][0]['group_name'] == 'Group 1'
        assert data["invitations"][1]['role'] == 'administrator'

    def test_get_user_groups(self, app, client, mock_auth, sample_groups, sample_memberships):
        """Test getting current user's groups"""
        mock_group_manager = app.config['GROUP_MANAGER']
        
        user_groups = [
            (sample_groups[0], sample_memberships[0]),
            (sample_groups[1], GroupMembership(
                group_id="group2",
                user_id="test_user_123",
                user_email="test@example.com",
                role=GroupRole.ADMINISTRATOR
            ))
        ]
        
        mock_group_manager.get_user_groups.return_value = user_groups
        mock_group_manager.get_group_members.return_value = []
        
        response = client.get('/groups/my')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["groups"]) == 2
        assert data["groups"][0]['name'] == 'Group 1'
        assert data["groups"][1]['name'] == 'Group 2'

    def test_leave_group(self, app, client, mock_auth):
        """Test leaving a group"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = False  # User is not manager
        mock_group_manager.remove_member.return_value = True
        
        leave_data = {"user_id": "test_user_123"}
        
        response = client.delete('/groups/group1/members',
                               data=json.dumps(leave_data),
                               content_type='application/json')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "removed"
        mock_group_manager.remove_member.assert_called_once_with('group1', 'test_user_123')

    def test_leave_group_failure(self, app, client, mock_auth):
        """Test leaving group when removal fails"""
        mock_group_manager = app.config['GROUP_MANAGER']
        mock_group_manager.user_can_manage_group.return_value = False  # User is not manager
        mock_group_manager.remove_member.return_value = False
        
        leave_data = {"user_id": "test_user_123"}
        
        response = client.delete('/groups/group1/members',
                               data=json.dumps(leave_data),
                               content_type='application/json')
        
        assert response.status_code == 404

    def test_get_group_summary(self, app, client, mock_auth):
        """Test getting group summary (non-existent endpoint)"""
        response = client.get('/groups/group1/summary')
        assert response.status_code == 404

    def test_get_group_summary_not_member(self, app, client, mock_auth):
        """Test getting group summary when not a member (non-existent endpoint)"""
        response = client.get('/groups/group1/summary')
        assert response.status_code == 404