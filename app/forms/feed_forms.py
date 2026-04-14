from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, TextAreaField
from wtforms.validators import InputRequired, Length, Optional


class FeedPostForm(FlaskForm):
    content = TextAreaField("Message", validators=[InputRequired(), Length(max=2000)])
    is_decision = BooleanField("Mark as decision")
    attachment = FileField(
        "Attachment",
        validators=[
            Optional(),
            FileAllowed(["pdf", "jpg", "jpeg", "png", "gif", "docx", "xlsx", "txt"], "File type not allowed."),
        ],
    )


class FeedReplyForm(FlaskForm):
    content = TextAreaField("Reply", validators=[InputRequired(), Length(max=2000)])
