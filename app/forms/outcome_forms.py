from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, TextAreaField
from wtforms.validators import InputRequired, Length, NumberRange, Optional


class OutcomeReportForm(FlaskForm):
    outcome_achieved = TextAreaField("Outcome Achieved", validators=[InputRequired(), Length(min=50)])
    measurable_data = TextAreaField("Measurable Data", validators=[Optional(), Length(max=3000)])
    team_size_actual = IntegerField("Team Size", validators=[InputRequired(), NumberRange(min=1, max=200)])
    total_hours_estimated = IntegerField("Total Hours", validators=[InputRequired(), NumberRange(min=1, max=100000)])
    unexpected_challenges = TextAreaField("Unexpected Challenges", validators=[InputRequired(), Length(min=20)])
    lessons_learned = TextAreaField("Lessons Learned", validators=[InputRequired(), Length(min=20)])
    would_recommend = BooleanField("Would recommend this approach?")
    was_continued = BooleanField("Project continued beyond timeline?")
    continuation_description = TextAreaField("Continuation Description", validators=[Optional(), Length(max=2000)])


class PeerRatingForm(FlaskForm):
    # Dynamic per-teammate rating inputs are validated in the route.
    # Keeping this form CSRF-only prevents false validation failures.
    pass
