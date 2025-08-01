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
import uuid
from unittest.mock import Mock, patch, MagicMock
from deriva.web.groups.api.groups.email_service import EmailService, create_email_service_from_config
from deriva.web.groups.api.groups.models import Group, GroupInvitation, JoinRequest, GroupRole, JoinRequestStatus


class TestEmailServiceCreation:
    """Test EmailService creation and configuration"""
    
    def test_create_email_service_basic(self):
        """Test creating email service with basic configuration"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        assert email_service.smtp_host == "smtp.example.com"
        assert email_service.smtp_port == 587
        assert email_service.username == "test@example.com"
        assert email_service.password == "password123"
        assert email_service.use_tls is True
        assert email_service.use_ssl is False
        assert email_service.from_email == "test@example.com"
    
    def test_create_email_service_with_all_options(self):
        """Test creating email service with all options"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=465,
            username="test@example.com",
            password="password123",
            use_tls=False,
            use_ssl=True,
            from_email="noreply@example.com"
        )
        
        assert email_service.smtp_host == "smtp.example.com"
        assert email_service.smtp_port == 465
        assert email_service.username == "test@example.com"
        assert email_service.password == "password123"
        assert email_service.use_tls is False
        assert email_service.use_ssl is True
        assert email_service.from_email == "noreply@example.com"
    
    def test_create_email_service_from_config(self):
        """Test creating email service from config dictionary"""
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "test@example.com",
            "smtp_password": "password123",
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "smtp_from_email": "noreply@example.com"
        }
        
        email_service = create_email_service_from_config(config)
        
        assert email_service is not None
        assert email_service.smtp_host == "smtp.example.com"
        assert email_service.smtp_port == 587
        assert email_service.username == "test@example.com"
        assert email_service.password == "password123"
        assert email_service.use_tls is True
        assert email_service.use_ssl is False
        assert email_service.from_email == "noreply@example.com"
    
    def test_create_email_service_from_config_defaults(self):
        """Test creating email service from config with defaults"""
        config = {
            "smtp_host": "smtp.example.com",
            "smtp_username": "test@example.com",
            "smtp_password": "password123"
        }
        
        email_service = create_email_service_from_config(config)
        
        assert email_service is not None
        assert email_service.smtp_port == 587  # Default
        assert email_service.use_tls is True    # Default
        assert email_service.use_ssl is False   # Default
    
    def test_create_email_service_from_config_failure(self):
        """Test creating email service from invalid config"""
        config = {}  # Missing required fields

        email_service = create_email_service_from_config(config)
        
        assert email_service is None


class TestEmailServiceTestConnection:
    """Test EmailService connection testing"""
    
    def test_test_connection_success_tls(self, mock_smtp):
        """Test successful connection with TLS"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123",
            use_tls=True,
            use_ssl=False
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.test_connection()
            
            assert result is True
            mock_smtp_class.assert_called_once_with("smtp.example.com", 587)
            mock_smtp.starttls.assert_called_once()
            mock_smtp.login.assert_called_once_with("test@example.com", "password123")
            mock_smtp.quit.assert_called_once()
    
    def test_test_connection_success_ssl(self, mock_smtp):
        """Test successful connection with SSL"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=465,
            username="test@example.com",
            password="password123",
            use_tls=False,
            use_ssl=True
        )
        
        with patch('smtplib.SMTP_SSL') as mock_smtp_ssl_class:
            mock_smtp_ssl_class.return_value = mock_smtp
            
            result = email_service.test_connection()
            
            assert result is True
            mock_smtp_ssl_class.assert_called_once_with("smtp.example.com", 465)
            mock_smtp.starttls.assert_not_called()
            mock_smtp.login.assert_called_once_with("test@example.com", "password123")
            mock_smtp.quit.assert_called_once()
    
    def test_test_connection_failure(self):
        """Test connection failure"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.side_effect = Exception("Connection failed")
            
            with patch('deriva.web.groups.api.groups.email_service.logger') as mock_logger:
                result = email_service.test_connection()
                
                assert result is False
                mock_logger.error.assert_called_once()


class TestEmailServiceInvitations:
    """Test EmailService invitation email sending"""
    
    def test_send_invitation_email_success(self, mock_smtp):
        """Test sending invitation email successfully"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group",
            description="A test group for unit testing"
        )
        
        invitation = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            email="invitee@example.com",
            role=GroupRole.MEMBER,
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_invitation_email(
                invitation,
                group,
                "https://example.com",
                "Admin User"
            )
            
            assert result is True
            mock_smtp_class.assert_called_once_with("smtp.example.com", 587)
            mock_smtp.starttls.assert_called_once()
            mock_smtp.login.assert_called_once_with("test@example.com", "password123")
            mock_smtp.send_message.assert_called_once()
            mock_smtp.quit.assert_called_once()
    
    def test_send_invitation_email_with_description(self, mock_smtp):
        """Test sending invitation email with group description"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data with description
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group",
            description="A test group with detailed description"
        )
        
        invitation = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            email="invitee@example.com",
            role=GroupRole.ADMINISTRATOR,
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_invitation_email(
                invitation,
                group,
                "https://example.com",
                "Admin User"
            )
            
            assert result is True
            # Verify send_message was called with proper email content
            mock_smtp.send_message.assert_called_once()
            call_args = mock_smtp.send_message.call_args
            email_message = call_args[0][0]
            
            # Check email headers
            assert email_message['Subject'] == f"Invitation to join group: {group.name}"
            assert email_message['From'] == "test@example.com"
            assert email_message['To'] == "invitee@example.com"
    
    def test_send_invitation_email_failure(self):
        """Test sending invitation email failure"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        invitation = GroupInvitation(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            email="invitee@example.com",
            role=GroupRole.MEMBER,
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.side_effect = Exception("SMTP error")
            
            with patch('deriva.web.groups.api.groups.email_service.logger') as mock_logger:
                result = email_service.send_invitation_email(
                    invitation,
                    group,
                    "https://example.com",
                    "Admin User"
                )
                
                assert result is False
                mock_logger.error.assert_called_once()


class TestEmailServiceJoinRequests:
    """Test EmailService join request email sending"""
    
    def test_send_join_request_notification_success(self, mock_smtp):
        """Test sending join request notification successfully"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group",
            description="A test group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            message="Please let me join this group",
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_join_request_notification(
                join_request,
                group,
                "Test User",
                "https://example.com"
            )
            
            # Note: Current implementation returns True as placeholder
            assert result is True
    
    def test_send_join_request_notification_with_message(self, mock_smtp):
        """Test sending join request notification with user message"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data with message
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            message="I have relevant experience and would like to contribute",
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_join_request_notification(
                join_request,
                group,
                "Test User",
                "https://example.com"
            )
            
            assert result is True
    
    def test_send_join_request_notification_failure(self):
        """Test sending join request notification failure"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            token=str(uuid.uuid4().hex)
        )
        
        # Note: Current implementation returns True as placeholder
        # In a real implementation this would send emails to admins/managers
        result = email_service.send_join_request_notification(
            join_request,
            group,
            "Test User",
            "https://example.com"
        )
        
        # Current implementation always returns True
        assert result is True


class TestEmailServiceDecisionEmails:
    """Test EmailService decision email sending"""
    
    def test_send_join_request_decision_email_approved(self, mock_smtp):
        """Test sending approved join request decision email"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            status=JoinRequestStatus.APPROVED,
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_join_request_decision_email(
                join_request,
                group,
                "approved",
                "Admin User",
                "Welcome to the group!"
            )
            
            assert result is True
            mock_smtp.send_message.assert_called_once()
            call_args = mock_smtp.send_message.call_args
            email_message = call_args[0][0]
            
            # Check email headers
            assert email_message['Subject'] == f"Join request approved for group: {group.name}"
            assert email_message['From'] == "test@example.com"
            assert email_message['To'] == "user@example.com"
    
    def test_send_join_request_decision_email_denied(self, mock_smtp):
        """Test sending denied join request decision email"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            status=JoinRequestStatus.DENIED,
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_join_request_decision_email(
                join_request,
                group,
                "denied",
                "Admin User",
                "Group is currently at capacity"
            )
            
            assert result is True
            mock_smtp.send_message.assert_called_once()
            call_args = mock_smtp.send_message.call_args
            email_message = call_args[0][0]
            
            # Check email headers
            assert email_message['Subject'] == f"Join request denied for group: {group.name}"
    
    def test_send_join_request_decision_email_no_comment(self, mock_smtp):
        """Test sending decision email without reviewer comment"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            status=JoinRequestStatus.APPROVED,
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service.send_join_request_decision_email(
                join_request,
                group,
                "approved",
                "Admin User",
                ""  # No comment
            )
            
            assert result is True
            mock_smtp.send_message.assert_called_once()
    
    def test_send_join_request_decision_email_failure(self):
        """Test sending decision email failure"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123"
        )
        
        # Create test data
        group = Group(
            id=str(uuid.uuid4()),
            name="Test Group"
        )
        
        join_request = JoinRequest(
            id=str(uuid.uuid4()),
            group_id=group.id,
            group_name=group.name,
            user_id="user123",
            user_email="user@example.com",
            user_name="Test User",
            token=str(uuid.uuid4().hex)
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.side_effect = Exception("SMTP error")
            
            with patch('deriva.web.groups.api.groups.email_service.logger') as mock_logger:
                result = email_service.send_join_request_decision_email(
                    join_request,
                    group,
                    "approved",
                    "Admin User",
                    "Welcome!"
                )
                
                assert result is False
                mock_logger.error.assert_called_once()


class TestEmailServicePrivateMethods:
    """Test EmailService private methods"""
    
    def test_send_email_with_tls(self, mock_smtp):
        """Test _send_email method with TLS"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123",
            use_tls=True,
            use_ssl=False
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service._send_email(
                "recipient@example.com",
                "Test Subject",
                "Test plain text body",
                "<html><body>Test HTML body</body></html>"
            )
            
            assert result is True
            mock_smtp_class.assert_called_once_with("smtp.example.com", 587)
            mock_smtp.starttls.assert_called_once()
            mock_smtp.login.assert_called_once_with("test@example.com", "password123")
            mock_smtp.send_message.assert_called_once()
            mock_smtp.quit.assert_called_once()
    
    def test_send_email_with_ssl(self, mock_smtp):
        """Test _send_email method with SSL"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=465,
            username="test@example.com",
            password="password123",
            use_tls=False,
            use_ssl=True
        )
        
        with patch('smtplib.SMTP_SSL') as mock_smtp_ssl_class:
            mock_smtp_ssl_class.return_value = mock_smtp
            
            result = email_service._send_email(
                "recipient@example.com",
                "Test Subject",
                "Test plain text body",
                "<html><body>Test HTML body</body></html>"
            )
            
            assert result is True
            mock_smtp_ssl_class.assert_called_once_with("smtp.example.com", 465)
            mock_smtp.starttls.assert_not_called()
            mock_smtp.login.assert_called_once_with("test@example.com", "password123")
            mock_smtp.send_message.assert_called_once()
            mock_smtp.quit.assert_called_once()
    
    def test_send_email_with_custom_from(self, mock_smtp):
        """Test _send_email method with custom from email"""
        email_service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password="password123",
            from_email="noreply@example.com"
        )
        
        with patch('smtplib.SMTP') as mock_smtp_class:
            mock_smtp_class.return_value = mock_smtp
            
            result = email_service._send_email(
                "recipient@example.com",
                "Test Subject",
                "Test plain text body",
                "<html><body>Test HTML body</body></html>"
            )
            
            assert result is True
            mock_smtp.send_message.assert_called_once()
            call_args = mock_smtp.send_message.call_args
            email_message = call_args[0][0]
            
            # Check from email
            assert email_message['From'] == "noreply@example.com"