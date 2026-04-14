from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField, TextAreaField
from wtforms.validators import InputRequired, Length, Optional


class TaskCreateForm(FlaskForm):
    title = StringField("Title", validators=[InputRequired(), Length(max=500)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    due_date = DateField("Due Date", validators=[Optional()])
    priority = SelectField(
        "Priority",
        choices=[("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
        validators=[InputRequired()],
    )
    assigned_to_user_id = SelectField("Assignee", coerce=int, validators=[Optional()])


class TaskUpdateForm(FlaskForm):
    title = StringField("Title", validators=[InputRequired(), Length(max=500)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    due_date = DateField("Due Date", validators=[Optional()])
    priority = SelectField(
        "Priority",
        choices=[("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
        validators=[InputRequired()],
    )
    status = SelectField(
        "Status",
        choices=[("todo", "To Do"), ("in_progress", "In Progress"), ("done", "Done")],
        validators=[InputRequired()],
    )
