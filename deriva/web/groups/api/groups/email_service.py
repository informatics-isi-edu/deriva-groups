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

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from .models import GroupInvitation, Group

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str, 
                 use_tls: bool = True, use_ssl: bool = False, from_email: Optional[str] = None):
        if not (smtp_host and smtp_port and username and password):
            raise ValueError("smtp_host, smtp_port, username and password are required to configure the EmailService")

        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.from_email = from_email or username

    def send_invitation_email(self, invitation: GroupInvitation, group: Group, 
                            base_url: str, invited_by_name: str = "Administrator") -> bool:
        """Send an invitation email to join a group"""
        try:
            # Create the invitation URL
            invitation_url = f"{base_url}/invitations"
            
            # Create email content
            subject = f"Invitation to join group: {group.name}"
            
            # HTML template
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Group Invitation</title>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                    .content {{ background-color: #ffffff; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px; }}
                    .button {{ display: inline-block; background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin: 20px 0; }}
                    .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #e9ecef; font-size: 12px; color: #6c757d; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>You've been invited to join a group!</h1>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p><strong>{invited_by_name}</strong> has invited you to join the group <strong>"{group.name}"</strong>.</p>
                        {f'<p><em>"{group.description}"</em></p>' if group.description else ''}
                        <p>Your role in this group will be: <strong>{invitation.role.value.title()}</strong></p>
                        <p>To accept this invitation and join the group, click the button below:</p>
                        <a href="{invitation_url}" class="button">Accept Invitation</a>
                        <p>Or copy and paste this link into your browser:</p>
                        <p><a href="{invitation_url}">{invitation_url}</a></p>
                        <p><strong>Note:</strong> This invitation will expire in 7 days.</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated message from DERIVA Group Management System.</p>
                        <p>If you did not expect this invitation, you can safely ignore this email.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Plain text version
            text_body = f"""
            You've been invited to join a group!
            
            {invited_by_name} has invited you to join the group "{group.name}".
            {f'Description: {group.description}' if group.description else ''}
            
            Your role in this group will be: {invitation.role.value.title()}
            
            To accept this invitation and join the group, visit:
            {invitation_url}
            
            Note: This invitation will expire in 7 days.
            
            This is an automated message from DERIVA Group Management System.
            If you did not expect this invitation, you can safely ignore this email.
            """
            
            return self._send_email(invitation.email, subject, text_body, html_body)
            
        except Exception as e:
            logger.error(f"Failed to send invitation email to {invitation.email}: {e}")
            return False

    def send_join_request_notification(self, join_request, group, requester_name: str, base_url: str) -> bool:
        """Send notification to group admins/managers about new join request"""
        try:
            # Create the review URL
            review_url = f"{base_url}/groups/{group.id}?tab=requests"
            
            subject = f"New join request for group: {group.name}"
            
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>New Join Request</title>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #e3f2fd; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                    .content {{ background-color: #ffffff; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px; }}
                    .button {{ display: inline-block; background-color: #2196f3; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin: 20px 0; }}
                    .user-info {{ background-color: #f8f9fa; padding: 15px; border-radius: 4px; margin: 15px 0; }}
                    .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #e9ecef; font-size: 12px; color: #6c757d; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>New Join Request</h1>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p>A user has requested to join your group <strong>"{group.name}"</strong>.</p>
                        
                        <div class="user-info">
                            <h3>Request Details:</h3>
                            <p><strong>User:</strong> {requester_name} ({join_request.user_email})</p>
                            {f'<p><strong>Message:</strong> {join_request.message}</p>' if join_request.message else ''}
                            <p><strong>Requested on:</strong> {join_request.created_at}</p>
                        </div>
                        
                        <p>Please review this request and approve or deny it.</p>
                        <a href="{review_url}" class="button">Review Request</a>
                        <p>Or copy and paste this link into your browser:</p>
                        <p><a href="{review_url}">{review_url}</a></p>
                    </div>
                    <div class="footer">
                        <p>This is an automated message from DERIVA Group Management System.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            text_body = f"""
            New Join Request
            
            A user has requested to join your group "{group.name}".
            
            Request Details:
            User: {requester_name} ({join_request.user_email})
            {f'Message: {join_request.message}' if join_request.message else ''}
            
            Please review this request at:
            {review_url}
            
            This is an automated message from DERIVA Group Management System.
            """
            
            # Note: This would need to be sent to all group admins/managers
            # For now, we'll need the caller to provide recipient emails
            return True  # Placeholder - actual implementation would send to admins/managers
            
        except Exception as e:
            logger.error(f"Failed to send join request notification: {e}")
            return False

    def send_join_request_decision_email(self, join_request, group, decision: str, reviewer_name: str, reviewer_comment: str = "") -> bool:
        """Send email to user about join request decision"""
        try:
            subject = f"Join request {decision} for group: {group.name}"
            
            if decision == "approved":
                color = "#28a745"
                decision_text = "approved"
                message = f"Congratulations! Your request to join the group <strong>'{group.name}'</strong> has been approved."
                action_text = "You can now access the group and participate in its activities."
            else:
                color = "#dc3545"
                decision_text = "denied"
                message = f"Unfortunately, your request to join the group <strong>'{group.name}'</strong> has been denied."
                action_text = "You may contact the group administrators if you have questions about this decision."
            
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Join Request {decision_text.title()}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: {color}; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                    .content {{ background-color: #ffffff; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px; }}
                    .comment {{ background-color: #f8f9fa; padding: 15px; border-radius: 4px; margin: 15px 0; border-left: 4px solid {color}; }}
                    .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #e9ecef; font-size: 12px; color: #6c757d; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Join Request {decision_text.title()}</h1>
                    </div>
                    <div class="content">
                        <p>Hello,</p>
                        <p>{message}</p>
                        <p>{action_text}</p>
                        
                        {f'<div class="comment"><p><strong>Comment from {reviewer_name}:</strong></p><p>{reviewer_comment}</p></div>' if reviewer_comment else ''}
                        
                        <p>Thank you for your interest in joining our community!</p>
                    </div>
                    <div class="footer">
                        <p>This is an automated message from DERIVA Group Management System.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            text_body = f"""
            Join Request {decision_text.title()}
            
            {message}
            {action_text}
            
            {f'Comment from {reviewer_name}: {reviewer_comment}' if reviewer_comment else ''}
            
            Thank you for your interest in joining our community!
            
            This is an automated message from DERIVA Group Management System.
            """
            
            return self._send_email(join_request.user_email, subject, text_body, html_body)
            
        except Exception as e:
            logger.error(f"Failed to send decision email to {join_request.user_email}: {e}")
            return False

    def _send_email(self, to_email: str, subject: str, text_body: str, html_body: str) -> bool:
        """Common email sending logic"""
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.from_email
        msg['To'] = to_email

        # Attach parts
        text_part = MIMEText(text_body, 'plain')
        html_part = MIMEText(html_body, 'html')

        msg.attach(text_part)
        msg.attach(html_part)

        # Send email
        if self.use_ssl:
            server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
        else:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            if self.use_tls:
                server.starttls()

        server.login(self.username, self.password)
        server.send_message(msg)
        server.quit()

        logger.debug(f"Email sent successfully to {to_email}")

        return True

    def test_connection(self) -> bool:
        """Test SMTP connection"""
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                if self.use_tls:
                    server.starttls()
            
            server.login(self.username, self.password)
            server.quit()
            logger.info("SMTP connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"SMTP connection test failed: {e}")
            return False


def create_email_service_from_config(config: dict) -> Optional[EmailService]:
    """Create EmailService from configuration"""
    try:
        return EmailService(
            smtp_host=config.get('smtp_host'),
            smtp_port=config.get('smtp_port', 587),
            username=config.get('smtp_username'),
            password=config.get('smtp_password'),
            use_tls=config.get('smtp_use_tls', True),
            use_ssl=config.get('smtp_use_ssl', False),
            from_email=config.get('smtp_from_email')
        )
    except Exception as e:
        logger.error(f"Failed to create email service: {e}")
        return None