#########################
# ICSB School Dashboard #
#########################
# author:    jbetley
# version:  1.09
# date:     08/13/23

# NOTE: Because of the way data is store and presented by IDOE, there are
# cases in which data points need to be manually calculated that the school
# level for data that is stored at the corporation level. Specifically, this
# is an issue for calculating demographic enrollment when there is a school
# that crosses natural grade span splits, e.g., Split Grade K8 and 912 enrollment using
# proportionate split for:
#   Christel House South (CHS/CHWMHS)
#   Circle City Prep (Ele/Mid)

# flask and flask-login #
# https://levelup.gitconnected.com/how-to-setup-user-authentication-for-dash-apps-using-python-and-flask-6c2e430cdb51
# https://community.plotly.com/t/dash-app-pages-with-flask-login-flow-using-flask/69507/38
# https://stackoverflow.com/questions/52286507/how-to-merge-flask-login-with-a-dash-application
# https://python-adv-web-apps.readthedocs.io/en/latest/flask_db2.html

import os
from flask import Flask, url_for, redirect, request, render_template, session, jsonify
from flask_login import login_user, LoginManager, UserMixin, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

import dash
from dash import dcc, html, Input, Output, callback
import dash_bootstrap_components as dbc
import pandas as pd
from pages.load_data import get_school_index, get_academic_dropdown_years, get_financial_info_dropdown_years, \
    get_school_dropdown_list, get_financial_analysis_dropdown_years, get_school_corporation_list, get_public_school_list

# Used to generate metric rating svg circles
FONT_AWESOME = "https://use.fontawesome.com/releases/v5.10.2/css/all.css"

external_stylesheets = ["https://fonts.googleapis.com/css2?family=Jost:400", FONT_AWESOME]
# external_stylesheets = ["https://fonts.googleapis.com/css2?family=Noto+Sans&display=swap", FONT_AWESOME]

# NOTE: Cannot get static folder to work (images do not load and give 302 Found error)
server = Flask(__name__, static_folder="static")

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))
server.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    basedir, "users.db"
)
server.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
server.config.update(SECRET_KEY=os.getenv("SECRET_KEY"))

bcrypt = Bcrypt()

db = SQLAlchemy(server)

login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = "/login"

# each table in the database needs a class to be created for it
# using the db.Model, all db columns must be identified by name
# and data type. UserMixin provides a get_id method that returns
# the id attribute or raises an exception.
class User(UserMixin, db.Model):    # type: ignore
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, unique=True)
    password = db.Column(db.Text, unique=True)

# load_user is used by login_user, passes the user_id
# and gets the User object that matches that id
@login_manager.user_loader
def load_user(id):
    return db.session.get(User, int(id))

# The default is to block all requests unless user is on login page or is authenticated
@server.before_request
def check_login():
    if request.method == "GET":
        if request.path in ["/login"]:
            return
        if current_user:
            if current_user.is_authenticated:
                return
            else:
                for pg in dash.page_registry:
                    if request.path == dash.page_registry[pg]["path"]:
                        session["url"] = request.url

        return redirect(url_for("login"))
    else:
        if current_user:
            if request.path == "/login" or current_user.is_authenticated:
                return
        return jsonify({"status": "401", "statusText": "unauthorized access"})

# Login logic
message = "Invalid username and/or password."

@server.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # if user is authenticated - redirect to dash app
        if current_user.is_authenticated:
            return redirect("/")

        # otherwise show the login page
        return render_template("login.html", message=message)

    if request.method == "POST":
        if request.form:
            user = request.form["username"]
            password = request.form["password"]

            # Get user_data from the User object matching the provided username
            user_data = User.query.filter_by(username=user).first()

            if user_data:
                # check a hash of the provided password against the hashed password stored in the
                # User object
                if bcrypt.check_password_hash(user_data.password, password):

                    # if True, login the user using the User object
                    login_user(user_data)

                    if "url" in session:
                        if session["url"]:
                            url = session["url"]
                            session["url"] = None
                            return redirect(url)  ## redirect to target url
                    return redirect("/")  ## redirect to home

    # Redirect to login page on error
    return redirect(url_for("login", error=1))

@server.route("/logout", methods=["GET"])
def logout():
    if current_user:
        if current_user.is_authenticated:
            logout_user()
    return render_template("login.html", message="You have been logged out.")

app = dash.Dash(
    __name__,
    server=server,
    use_pages=True,
    external_stylesheets=external_stylesheets,
    suppress_callback_exceptions=True,
    # compress=False, # testing
    meta_tags=[
    {
        "name": "viewport",
        "content": "width=device-width, initial-scale=1, maximum-scale=1",
    }
],
)
years = get_academic_dropdown_years()

@callback(
    Output("corporation-dropdown", "options"),
    Input("year-dropdown", "value")
)
def set_corp_dropdown_options(year):
    
    school_corporations = get_school_corporation_list(year)

    corp_dropdown_dict = dict(zip(school_corporations["Corporation Name"], school_corporations["Corporation ID"]))
    corp_dropdown_list = dict(sorted(corp_dropdown_dict.items()))
    corp_dropdown_options = [{"label": name, "value": id} for name, id in corp_dropdown_list.items()]

    return corp_dropdown_options

@callback(
    Output("corporation-dropdown", "value"),
    Input("corporation-dropdown", "options")
)
def set_corp_dropdown_value(corp_options):
    return corp_options[0]["value"]

@callback(
    Output("school-dropdown", "options"),
    Input("corporation-dropdown", "value")
)
def set_school_dropdown_options(corp):

    public_schools = get_public_school_list(corp)

        # public_schools = pd.concat([public_schools, school_group], axis=1, join="inner")

    school_dropdown_dict = dict(zip(public_schools["School Name"], public_schools["School ID"]))
    school_dropdown_list = dict(sorted(school_dropdown_dict.items()))
    school_dropdown_options = [{"label": name, "value": id} for name, id in school_dropdown_list.items()]

    return school_dropdown_options

@callback(
    Output("school-dropdown", "value"),
    Input("school-dropdown", "options")
)
def set_corp_dropdown_value(school_options):
    return school_options[0]["value"]

# app.layout = html.Div(    # NOTE: Test to see if it impacts speed
def layout():
    return html.Div(
        [
        
        html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                html.A("logout", href="../logout", className="logout-button"),
                            ],
                            className="bare_container_center one columns",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Label("Select Year:"),
                                    ],
                                    className="dash_label",
                                    id="year_dash_label",
                                ),
                                dcc.Dropdown(
                                    id = "year-dropdown",
                                    options = [{'label':x, 'value': x} for x in years],
                                    value = years[0],
                                    style={
                                        "fontFamily": "Jost, sans-serif",
                                        'color': 'steelblue',
                                    },
                                    multi=False,
                                    clearable=False,
                                    className="year_dash_control",
                                ),
                            ],
                            className="pretty_container three columns",
                        ),                        
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Label("Select School Corporation:"),
                                    ],
                                    className="dash_label",
                                    id="corp_dash_label",
                                ),
                                dcc.Dropdown(
                                    id="corporation-dropdown",
                                    style={
                                        "fontFamily": "Jost, sans-serif",
                                        'color': 'steelblue',
                                    },
                                    multi = True,
                                    clearable = True,
                                    className="school_dash_control",
                                ),
                            ],
                            className="pretty_container five columns",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Label("Select School(s):"),
                                    ],
                                    className="dash_label",
                                    id="school_dash_label",
                                ),
                                dcc.Dropdown(
                                    id="school-dropdown",
                                    style={
                                        "fontFamily": "Jost, sans-serif",
                                        'color': 'steelblue',
                                    },
                                    multi = True,
                                    clearable = True,
                                    className="school_dash_control",
                                ),
                            ],
                            className="pretty_container five columns",
                        ),                        
                    ],
                    className="fixed-row",
                ),
            ],
            className="fixed-row",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                dbc.Nav(
                                    [
                                        dbc.NavLink(
                                            page["name"],
                                            href=page["path"],
                                            className="tab",
                                            active="exact",
                                        )
                                        for page in dash.page_registry.values()
                                        if page.get("top_nav")
                                        if page["module"] != "pages.not_found_404"
                                    ],
                                    className="tabs",
                                ),
                            ],
                            className="bare_container_center twelve columns",
                                style={
                                    "padding": "50px",
                                    "paddingBottom": "60px",
                                    "marginTop": "50px",
                                }
                        ),
                    ],
                    className="row",
                ),
                dash.page_container,
            ],
        )
    ],
)

app.layout = layout # testing layout as a function - not sure its faster

if __name__ == "__main__":
    app.run_server(debug=True)
# #    application.run(host='0.0.0.0', port='8080')