import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import Email, EqualTo, InputRequired, Length, ValidationError

from app.models import User


def validate_strong_password(_form, field):
    password = field.data or ""
    if len(password) < 12:
        raise ValidationError("Password must be at least 12 characters long.")


EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")
EMAIL_DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*$")


def validate_login_email(_form, field):
    email = (field.data or "").strip().lower()

    if not email:
        raise ValidationError("Email is required.")

    if email.count("@") != 1:
        raise ValidationError("Enter a valid email address.")

    local_part, domain_part = email.split("@", 1)
    if not local_part or not domain_part:
        raise ValidationError("Enter a valid email address.")

    # Keep auth email parsing permissive so internal domains like .local also work.
    local_is_invalid = (
        local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or not EMAIL_LOCAL_RE.fullmatch(local_part)
    )
    domain_is_invalid = (
        domain_part.startswith(".")
        or domain_part.endswith(".")
        or ".." in domain_part
        or not EMAIL_DOMAIN_RE.fullmatch(domain_part)
    )

    if local_is_invalid or domain_is_invalid:
        raise ValidationError("Enter a valid email address.")

    field.data = email


class SignupForm(FlaskForm):
    account_type = SelectField(
        "Account Type",
        choices=[("individual", "Individual"), ("organization", "Organization")],
        validators=[InputRequired()],
    )
    first_name = StringField("First Name", validators=[InputRequired(), Length(max=100)])
    last_name = StringField("Last Name", validators=[Length(max=100)])
    username = StringField("Username", validators=[InputRequired(), Length(min=3, max=100)])
    email = StringField("Email", validators=[InputRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[InputRequired(), validate_strong_password])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[InputRequired(), EqualTo("password", message="Passwords must match.")],
    )
    terms_accepted = BooleanField("I agree to the terms", validators=[InputRequired()])
    submit = SubmitField("Create Account")

    def validate_email(self, field):
        normalized_email = (field.data or "").strip().lower()
        field.data = normalized_email
        if User.query.filter_by(email=normalized_email).first():
            raise ValidationError("Email already registered.")

    def validate_username(self, field):
        if User.query.filter_by(username=field.data.lower()).first():
            raise ValidationError("Username is already taken.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[InputRequired(), Length(max=255), validate_login_email])
    password = PasswordField("Password", validators=[InputRequired()])
    remember = BooleanField("Remember me")
    submit = SubmitField("Log In")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[InputRequired(), Length(max=255), validate_login_email])
    submit = SubmitField("Send Reset Link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[InputRequired(), validate_strong_password])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[InputRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Reset Password")
