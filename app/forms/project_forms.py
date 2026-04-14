from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import InputRequired, Length, NumberRange, Optional


class WizardStep1Form(FlaskForm):
    title = StringField("Project Title", validators=[InputRequired(), Length(max=500)])
    problem_statement = TextAreaField("Problem Statement", validators=[InputRequired(), Length(min=30)])
    domain = SelectField(
        "Domain",
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
        validators=[InputRequired()],
    )
    geographic_scope = SelectField(
        "Geographic Scope",
        choices=[
            ("neighborhood", "Neighborhood"),
            ("city", "City"),
            ("national", "National"),
            ("global", "Global"),
            ("remote_friendly", "Remote Friendly"),
        ],
        validators=[InputRequired()],
    )
    city = StringField("City", validators=[Optional(), Length(max=200)])
    country = StringField("Country", validators=[Optional(), Length(max=100)])
    latitude = FloatField("Latitude", validators=[Optional()])
    longitude = FloatField("Longitude", validators=[Optional()])
    submit = SubmitField("Save and Continue")


class WizardStep2Form(FlaskForm):
    project_type = SelectField(
        "Project Type",
        choices=[
            ("awareness", "Awareness"),
            ("research", "Research"),
            ("direct_service", "Direct Service"),
            ("advocacy", "Advocacy"),
            ("physical_change", "Physical Change"),
            ("digital_tool", "Digital Tool"),
            ("resource_redistribution", "Resource Redistribution"),
        ],
        validators=[InputRequired()],
    )
    submit = SubmitField("Save and Continue")


class WizardStep3Form(FlaskForm):
    success_definition = TextAreaField("Success Definition", validators=[InputRequired(), Length(min=20)])
    submit = SubmitField("Save and Continue")


class WizardStep4Form(FlaskForm):
    min_viable_team_size = IntegerField("Minimum Viable Team", validators=[InputRequired(), NumberRange(min=1, max=20)])
    submit = SubmitField("Save and Continue")


class WizardStep5Form(FlaskForm):
    timeline_days = SelectField(
        "Timeline",
        choices=[("30", "30 days"), ("60", "60 days"), ("90", "90 days"), ("custom", "Custom Date")],
        validators=[InputRequired()],
    )
    start_date = DateField("Start Date", validators=[InputRequired()])
    custom_end_date = DateField("Custom End Date", validators=[Optional()])
    submit = SubmitField("Save and Continue")


class WizardStep6Form(FlaskForm):
    resources_needed = TextAreaField("Resources Needed", validators=[Optional(), Length(max=2000)])
    estimated_budget = StringField("Estimated Budget", validators=[Optional(), Length(max=100)])
    submit = SubmitField("Save and Continue")
