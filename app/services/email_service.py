from flask import current_app
from flask_mail import Message

from app.extensions import mail


def _base_email_html(heading: str, body_html: str, action_text: str = "", action_url: str = "") -> str:
    button = ""
    if action_text and action_url:
        button = (
            f"<p style='margin:24px 0;'><a href='{action_url}' "
            "style='background:#E67E22;color:#fff;padding:12px 18px;text-decoration:none;border-radius:6px;display:inline-block;'>"
            f"{action_text}</a></p>"
        )

    return f"""
    <div style='font-family:Arial,sans-serif;background:#F8F9FA;padding:20px;'>
      <div style='max-width:620px;margin:0 auto;background:#fff;border:1px solid #E8E8E8;border-radius:10px;padding:24px;'>
        <h2 style='margin:0 0 10px;color:#145A32;'>Quorum</h2>
        <h3 style='color:#1A252F;'>{heading}</h3>
        <div style='color:#1A252F;line-height:1.6;'>{body_html}</div>
        {button}
        <hr style='border:none;border-top:1px solid #E8E8E8;margin:22px 0;'>
        <p style='font-size:12px;color:#5D6D7E;'>You're receiving this because you're a Quorum member. <a href='#' style='color:#5D6D7E;'>Unsubscribe</a></p>
      </div>
    </div>
    """


def _send(to_email: str, subject: str, html: str):
    if not to_email:
        return
    msg = Message(subject=subject, recipients=[to_email], html=html)
    mail.send(msg)


def send_verification_email(user, token):
    verify_url = f"{current_app.config['BASE_URL']}/verify/{token}"
    html = _base_email_html(
        "Verify your email",
        f"<p>Welcome {user.first_name}, verify your account to start publishing projects.</p>",
        "Verify Email",
        verify_url,
    )
    _send(user.email, "Verify your Quorum account", html)


def send_password_reset_email(user, token):
    reset_url = f"{current_app.config['BASE_URL']}/reset/{token}"
    html = _base_email_html(
        "Reset your password",
        "<p>Use the button below to reset your password. This link expires in 1 hour.</p>",
        "Reset Password",
        reset_url,
    )
    _send(user.email, "Reset your Quorum password", html)


def send_application_received(creator, applicant, project, role):
    html = _base_email_html(
        "New role application",
        f"<p>{applicant.full_name} applied for <strong>{role.title}</strong> on {project.title}.</p>",
        "Review Application",
        f"{current_app.config['BASE_URL']}/my-projects/{project.id}/team",
    )
    _send(creator.email, f"New application for {role.title}", html)


def send_application_accepted(applicant, project, role):
    html = _base_email_html(
        "Application accepted",
        f"<p>Your application for <strong>{role.title}</strong> in {project.title} was accepted.</p>",
        "Open Project",
        f"{current_app.config['BASE_URL']}/projects/{project.id}",
    )
    _send(applicant.email, "Your application was accepted", html)


def send_application_declined(applicant, project, role, message):
    body = f"<p>Your application for <strong>{role.title}</strong> in {project.title} was declined.</p>"
    if message:
        body += f"<p>Message: {message}</p>"
    html = _base_email_html("Application update", body)
    _send(applicant.email, "Your application status changed", html)


def send_mvt_alert(user, project):
    html = _base_email_html(
        "Project is launch-ready",
        f"<p>{project.title} has reached its minimum viable team threshold.</p>",
        "Open Dashboard",
        f"{current_app.config['BASE_URL']}/my-projects/{project.id}/manage",
    )
    _send(user.email, "Your project can now launch", html)


def send_launch_notification(team_member, project):
    html = _base_email_html(
        "Project launched",
        f"<p>{project.title} is now active.</p>",
        "Open Task Board",
        f"{current_app.config['BASE_URL']}/my-projects/{project.id}/tasks",
    )
    _send(team_member.email, "Project is now active", html)


def send_completion_rating_prompt(team_member, project):
    html = _base_email_html(
        "Rate your teammates",
        f"<p>{project.title} is complete. Please submit peer ratings.</p>",
        "Rate Team",
        f"{current_app.config['BASE_URL']}/projects/{project.id}/rate",
    )
    _send(team_member.email, "Please rate your teammates", html)


def send_outcome_approved(creator, project):
    html = _base_email_html(
        "Outcome report approved",
        f"<p>Your outcome report for {project.title} has been approved and published.</p>",
        "View Project",
        f"{current_app.config['BASE_URL']}/projects/{project.id}",
    )
    _send(creator.email, "Outcome report approved", html)


def send_weekly_digest(team_member, project, digest_data):
    html = _base_email_html(
        f"Weekly digest: {project.title}",
        f"""
        <p><strong>Due this week:</strong> {digest_data.get('due_this_week', 0)}</p>
        <p><strong>Completed last week:</strong> {digest_data.get('done_last_week', 0)}</p>
        <p><strong>Overdue tasks:</strong> {digest_data.get('overdue', 0)}</p>
        <p><strong>Upcoming milestones:</strong> {digest_data.get('milestones', 0)}</p>
        """,
        "Open Task Board",
        f"{current_app.config['BASE_URL']}/my-projects/{project.id}/tasks",
    )
    _send(team_member.email, f"Weekly digest for {project.title}", html)


def send_challenge_submission_received(org_user, challenge, submission):
    """Notify org when a new submission arrives for their challenge."""
    manage_url = f"{current_app.config['BASE_URL']}/org/challenges/{challenge.id}"
    summary = (submission.approach_summary or "").strip()
    if len(summary) > 300:
        summary = f"{summary[:300]}..."

    html = _base_email_html(
        f"New submission for {challenge.title}",
        (
            f"<p><strong>Submitter:</strong> {submission.submitter.full_name}</p>"
            f"<p><strong>Team:</strong> {submission.team_name}</p>"
            f"<p><strong>Approach summary:</strong> {summary}</p>"
        ),
        "Review Submission",
        manage_url,
    )
    _send(org_user.email, f"New submission for {challenge.title}", html)


def send_challenge_submission_confirmed(submitter, challenge):
    """Confirm to submitter that their solution was received."""
    submissions_url = f"{current_app.config['BASE_URL']}/challenges/my-submissions"
    html = _base_email_html(
        f"Your submission to {challenge.title} is received",
        (
            f"<p>Thanks for submitting your solution for <strong>{challenge.title}</strong>.</p>"
            f"<p>We'll notify you when the organization updates your submission status.</p>"
            f"<p><strong>Deadline reminder:</strong> {challenge.deadline.strftime('%d %b %Y') if challenge.deadline else 'N/A'}</p>"
        ),
        "View My Submissions",
        submissions_url,
    )
    _send(submitter.email, f"Your submission to {challenge.title} is received", html)


def send_challenge_status_update(submitter, challenge, new_status, org_feedback=None):
    """Notify submitter when org changes their submission status."""
    submissions_url = f"{current_app.config['BASE_URL']}/challenges/my-submissions"
    readable_status = str(new_status or "submitted").replace("_", " ").title()

    feedback_html = ""
    if org_feedback:
        feedback_html = f"<p><strong>Organization feedback:</strong> {org_feedback}</p>"

    html = _base_email_html(
        f"[Status Update] Your submission for {challenge.title}",
        (
            f"<p>Your submission status is now <strong>{readable_status}</strong>.</p>"
            f"{feedback_html}"
            "<p>You can view the latest details from your submissions dashboard.</p>"
        ),
        "Open My Submissions",
        submissions_url,
    )
    _send(submitter.email, f"[Status Update] Your submission for {challenge.title}", html)
