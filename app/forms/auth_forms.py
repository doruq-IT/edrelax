# app/forms/auth_forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length

class SignUpForm(FlaskForm):
    first_name = StringField("First Name", validators=[DataRequired(), Length(max=100)])
    last_name = StringField("Last Name", validators=[DataRequired(), Length(max=100)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=150)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirm Password", validators=[
        DataRequired(),
        EqualTo("password", message="Passwords must match.")
    ])
    updates = BooleanField("Receive Updates")
    terms = BooleanField("Agree to Terms", validators=[DataRequired()])

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")

