from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, IntegerField, SelectMultipleField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional


class EditProfileForm(FlaskForm):
    bio = TextAreaField("Bio", validators=[Optional(), Length(max=2000)])
    city = StringField("City", validators=[Optional(), Length(max=200)])
    country = StringField("Country", validators=[Optional(), Length(max=100)])
    availability_hours = IntegerField("Availability", validators=[Optional(), NumberRange(min=1, max=80)])
    is_open_to_projects = BooleanField("Open to projects")
    domain_interests = SelectMultipleField(
        "Domain Interests",
        choices=[
            ("environment", "Environment"),
            ("community", "Community"),
            ("education", "Education"),
            ("health", "Health"),
            ("civic_infrastructure", "Civic Infrastructure"),
            ("digital_access", "Digital Access"),
            ("food", "Food"),
            ("housing", "Housing"),
            ("other", "Other"),
        ],
    )
    skills = SelectMultipleField("Skills", coerce=int)
    profile_photo = FileField(
        "Profile Photo",
        validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "gif"], "Images only")],
    )


class OnboardingForm(FlaskForm):
    city = StringField("City", validators=[InputRequired(), Length(max=200)])
    country = StringField("Country", validators=[InputRequired(), Length(max=100)])
    availability_hours = IntegerField("Availability", validators=[InputRequired(), NumberRange(min=1, max=80)])
    is_open_to_projects = BooleanField("Open to projects")
    domain_interests = SelectMultipleField(
        "Domain Interests",
        validators=[DataRequired(message="Select at least one domain interest.")],
        choices=[
            ("environment", "Environment"),
            ("community", "Community"),
            ("education", "Education"),
            ("health", "Health"),
            ("civic_infrastructure", "Civic Infrastructure"),
            ("digital_access", "Digital Access"),
            ("food", "Food"),
            ("housing", "Housing"),
            ("other", "Other"),
        ],
    )
    skills = SelectMultipleField("Skills", coerce=int, validators=[DataRequired(message="Select at least one skill.")])
