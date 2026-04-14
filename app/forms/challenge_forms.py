from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, URL


class ChallengeSubmitForm(FlaskForm):
    team_name = StringField(
        "Team Name",
        validators=[DataRequired(), Length(min=2, max=300)],
        render_kw={"placeholder": "e.g. Ahmedabad Water Warriors"},
    )

    approach_summary = TextAreaField(
        "Approach Summary",
        validators=[DataRequired(), Length(min=100, max=1000)],
        render_kw={
            "placeholder": (
                "Describe your solution approach in 100-1000 characters. "
                "What will you do, how, and what outcome do you expect?"
            ),
            "rows": 6,
        },
    )

    linked_project_id = SelectField(
        "Link a Quorum Project (optional)",
        coerce=int,
        validators=[Optional()],
    )

    external_link = StringField(
        "Demo / Repository Link (optional)",
        validators=[Optional(), URL(), Length(max=500)],
        render_kw={"placeholder": "https://"},
    )

    proposal_document = FileField(
        "Upload Proposal (PDF or DOCX, max 10MB)",
        validators=[Optional(), FileAllowed(["pdf", "docx"], "PDF or DOCX only")],
    )

    team_members_text = TextAreaField(
        "Team Member Usernames (one per line, optional)",
        validators=[Optional(), Length(max=500)],
        render_kw={"placeholder": "Enter Quorum usernames of your team members", "rows": 3},
    )

    agree_terms = BooleanField(
        "I confirm this submission is original work and I have the right to submit it",
        validators=[DataRequired(message="You must confirm this to submit")],
    )
