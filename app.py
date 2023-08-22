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
from dash import ctx, dcc, html, Input, Output, callback
from dash.exceptions import PreventUpdate
import pandas as pd

# import local functions
from pages.load_data import ethnicity, subgroup, ethnicity, info_categories, get_academic_data, \
    get_school_coordinates, get_k8_corporation_academic_data, get_academic_dropdown_years, get_school_corporation_list, get_public_school_list
from pages.process_data import process_k8_academic_data, process_k8_corp_academic_data
from pages.calculations import find_nearest, calculate_proficiency, recalculate_total_proficiency, get_excluded_years
from pages.chart_helpers import no_data_fig_label, make_line_chart, make_bar_chart, make_group_bar_chart
from pages.table_helpers import create_comparison_table, no_data_page, no_data_table, combine_group_barchart_and_table, \
    combine_barchart_and_table
from pages.string_helpers import create_school_label, identify_missing_categories, combine_school_name_and_grade_levels, \
    create_school_label, create_chart_label
from pages.calculate_metrics import calculate_k8_comparison_metrics
from pages.subnav import subnav_academic


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
    # use_pages=True,
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
    Output("corporation-dropdown", "value"),
    Input("year-dropdown", "value"),
    Input("corporation-dropdown", "value"),
)
def set_corp_dropdown_options(year, corp_value):

    school_corporations = get_school_corporation_list(year)

    corp_dropdown_dict = dict(zip(school_corporations["Corporation Name"], school_corporations["Corporation ID"]))
    corp_dropdown_list = dict(sorted(corp_dropdown_dict.items()))
    corp_dropdown_options = [{"label": name, "value": id} for name, id in corp_dropdown_list.items()]

    if not corp_value:
        corp_dropdown_values = []
    else:
        corp_dropdown_values = corp_value

    return corp_dropdown_options, corp_dropdown_values

@callback(
    Output("school-dropdown", "options"),
    Output("school-dropdown", "value"),
    Input("corporation-dropdown", "value"),
    Input("school-dropdown", "value")
)
def set_school_dropdown_options(selected_corp, selected_schools):

    if not selected_schools:
        school_dropdown_values = []
    else:
        school_dropdown_values = selected_schools

    public_schools = get_public_school_list(selected_corp)

    # options
    school_dropdown_dict = dict(zip(public_schools["School Name"], public_schools["School ID"]))
    school_dropdown_list = dict(sorted(school_dropdown_dict.items()))
    school_dropdown_options = [{"label": name, "value": id} for name, id in school_dropdown_list.items()]

    # values
    num_schools = public_schools.groupby(['Corporation ID'])['School ID'].nunique()

    if isinstance(selected_corp, str):
        selected_corp = [selected_corp]
    
    for c in selected_corp:

        # if the school corporation has one school, auto add it to values
        if num_schools[int(c)] == 1:
            school_id = public_schools.loc[public_schools['Corporation ID'] == int(c), 'School ID'].values[0]
            if school_id not in school_dropdown_values:
                school_dropdown_values.append(school_id)

    return school_dropdown_options, school_dropdown_values


@callback(
    # Output("fig14a", "children"),
    # Output("fig14b", "children"),
    Output("fig14c", "children"),
    Output("fig14d", "children"),
    Output("fig-iread", "children"),
    # Output("fig16c1", "children"),
    # Output("fig16d1", "children"),
    # Output("fig16c2", "children"),
    # Output("fig16d2", "children"),
    # Output("fig14g", "children"),
    # Output("dropdown-container", "style"),
    Output("fig16a1", "children"),   
    Output("fig16a1-container", "style"),    
    Output("fig16b1", "children"),
    Output("fig16b1-container", "style"),
    Output("fig16a2", "children"),
    Output("fig16a2-container", "style"),
    Output("fig16b2", "children"),
    Output("fig16b2-container", "style"),
    Output("academic-analysis-main-container", "style"),
    Output("academic-analysis-empty-container", "style"),
    Output("academic-analysis-no-data", "children"),
    Input("year-dropdown", "value"),
    [Input("school-dropdown", "value"),]
)
def update_academic_analysis(year: str, school_list: list):
    if not school_list:
        raise PreventUpdate

    school_name = "Scooby Doo!"

    # show 2019 instead of 2020 as 2020 has no academic data
    string_year = "2019" if year == "2020" else year
    numeric_year = int(string_year)

    # default values (only empty container displayed)
    fig14c = []
    fig14d = []
    fig_iread = []
        
    fig16a1 = []
    fig16a1_container = {"display": "none"}

    fig16b1 = []
    fig16b1_container = {"display": "none"}

    fig16a2 = []
    fig16a2_container = {"display": "none"}

    fig16b2 = []
    fig16b2_container = {"display": "none"}

    academic_analysis_main_container = {"display": "none"}
    academic_analysis_empty_container = {"display": "block"}

    no_data_to_display = no_data_page("Academic Analysis")
     
   # get academic data
    raw_k8_school_data = get_academic_data(school_list,year)

    # excluded_years = get_excluded_years(year)

    raw_k8_school_data = raw_k8_school_data.replace({"^": "***"})

    k8_school_data = process_k8_academic_data(raw_k8_school_data)

    # raw_comparison_data = calculate_k8_comparison_metrics(clean_school_data, clean_corp_data, string_year)

    # if not clean_school_data.empty:

    #     raw_corp_data = get_k8_corporation_academic_data(school)

    #     corp_name = raw_corp_data["Corporation Name"].values[0]

    #     clean_corp_data = process_k8_corp_academic_data(raw_corp_data, clean_school_data)

    # tested_year = string_year + "School"

    # In addition, page is empty if the school is a K8/K12, and the df has data, but the tested_year
    # (YEARSchool) does not exist in the dataframe- this catches any year with no data (e.g., 2020) OR
    # if the tested header does exist, but all data in the column is NaN- this catches any year where
    # the school has no data or insufficient n-size ("***")

    # raw_comparison_data['Test Year'] = pd.to_numeric(raw_comparison_data[tested_year], errors="coerce")

    # if raw_comparison_data['Test Year'].isnull().all():
    #     no_data_to_display = no_data_page("Academic Analysis","No Available Data with a sufficient n-size.")
    
    # elif tested_year in raw_comparison_data.columns:

    academic_analysis_main_container = {"display": "block"}            
    academic_analysis_empty_container = {"display": "none"}

    # raw_comparison_data = raw_comparison_data.drop('Test Year', axis=1)

    # ## Year over Year figs
    # school_academic_data = raw_comparison_data[[col for col in raw_comparison_data.columns if "School" in col or "Category" in col]].copy()
    # school_academic_data.columns = school_academic_data.columns.str.replace(r"School$", "", regex=True)

    display_academic_data = k8_school_data.set_index("Category").T.rename_axis("School Name").rename_axis(None, axis=1).reset_index()

    # print(display_academic_data)
    # # add suffix to certain Categories
    # display_academic_data = display_academic_data.rename(columns={c: c + " Proficient %" for c in display_academic_data.columns if c not in ["Year", "School Name"]})

    # yearly_school_data = display_academic_data.copy()
    # yearly_school_data["School Name"] = school_name

    # ## Comparison data ##
    # current_school_data = display_academic_data.loc[display_academic_data["Year"] == string_year].copy()

    # this time we want to force '***' to NaN
    # for col in current_school_data.columns:
    #     current_school_data[col]=pd.to_numeric(current_school_data[col], errors="coerce")

    # current_school_data = current_school_data.dropna(axis=1, how="all")
    # current_school_data["School Name"] = school_name

# TODO: May want to add this back
    # Grade range data is used for the chart "hovertemplate"            
    # current_school_data["Low Grade"] =  selected_raw_k8_school_data.loc[(selected_raw_k8_school_data["Year"] == numeric_year), "Low Grade"].values[0]
    # current_school_data["High Grade"] =  selected_raw_k8_school_data.loc[(selected_raw_k8_school_data["Year"] == numeric_year), "High Grade"].values[0]


# TODO: May want to add this back
    # process academic data for the school corporation in which the selected school is located
    # corp_academic_data = clean_corp_data.set_index("Category").T.rename_axis("Year").rename_axis(None, axis=1).reset_index()
    # current_corp_data = corp_academic_data.loc[corp_academic_data["Year"] == string_year].copy()

    # for col in current_corp_data.columns:
    #     current_corp_data[col]=pd.to_numeric(current_corp_data[col], errors="coerce")

    # comparison_schools_filtered = get_comparable_schools(comparison_school_list, numeric_year)

    # comparison_schools_filtered = comparison_schools_filtered.filter(regex = r"Total Tested$|Total Proficient$|^IREAD Pass N|^IREAD Test N|Year|School Name|School ID|Distance|Low Grade|High Grade",axis=1)

    # # create list of columns with no data (used in loop below)
    # comparison_schools_info = comparison_schools_filtered[["School Name","Low Grade","High Grade"]].copy()            
    # comparison_schools_filtered = comparison_schools_filtered.drop(["School ID","School Name","Low Grade","High Grade"], axis=1)

    # # change values to numeric
    # for col in comparison_schools_filtered.columns:
    #     comparison_schools_filtered[col] = pd.to_numeric(comparison_schools_filtered[col], errors="coerce")

    # comparison_schools = calculate_proficiency(comparison_schools_filtered)

# TODO: ADD THIS BACK
    # comparison_schools = recalculate_total_proficiency(comparison_schools, clean_school_data)

    # # calculate IREAD Pass %
    # if "IREAD Proficient %" in current_school_data:
    #     comparison_schools["IREAD Proficient %"] = comparison_schools["IREAD Pass N"] / comparison_schools["IREAD Test N"]
    
    # # remove columns used to calculate the final proficiency (Total Tested and Total Proficient)
    # comparison_schools = comparison_schools.filter(regex = r"\|ELA Proficient %$|\|Math Proficient %$|^IREAD Proficient %|^Year$",axis=1)

    # # drop all columns from the comparison dataframe that aren't in the school dataframe

    # because the school file has already been processed, column names will not directly
    # match, so we create a list of unique substrings from the column names and use it
    # to filter the comparison set
    # valid_columns = current_school_data.columns.str.split("|").str[0].tolist()

    # comparison_schools = comparison_schools.filter(regex="|".join(valid_columns))

    # # drop any rows where all values in tested cols (proficiency data) are null (remove "Year" from column
    # # list because "Year" will never be null)
    # tested_columns = comparison_schools.columns.tolist()
    # tested_columns.remove("Year")
    # comparison_schools = comparison_schools.dropna(subset=tested_columns,how="all")

    # # add text info columns back
    # comparison_schools = pd.concat([comparison_schools, comparison_schools_info], axis=1, join="inner")

    # # reset indicies
    # comparison_schools = comparison_schools.reset_index(drop=True)

    #### Current Year ELA Proficiency Compared to Similar Schools (1.4.c) #
    category = "School Total|ELA Proficient %"

    # Get school value for specific category
    if category in display_academic_data.columns:

        fig14c_k8_data = display_academic_data[info_categories + [category]].copy()

        # add corp average for category to dataframe - note we are using 'clean_corp_data'
        # because the 'Corp' values have been dropped from raw_comparison_data
        # fig14c_k8_school_data.loc[len(fig14c_k8_school_data.index)] = \
        #     [corp_name,"3","8",clean_corp_data[clean_corp_data['Category'] == category][string_year].values[0]]

        # fig14c_comp_data = comparison_schools[info_categories + [category]]

        # # Combine data, fix dtypes, and send to chart function
        # fig14c_all_data = pd.concat([fig14c_k8_school_data,fig14c_comp_data])

        fig14c_table_data = fig14c_k8_data.copy()

        fig14c_k8_data[category] = pd.to_numeric(fig14c_k8_data[category])

        fig14c_chart = make_bar_chart(fig14c_k8_data, category, "Comparison: Current Year ELA Proficiency")

        fig14c_table_data["School Name"] = create_school_label(fig14c_table_data)

        fig14c_table_data = fig14c_table_data[["School Name", category]]
        fig14c_table_data = fig14c_table_data.reset_index(drop=True)

        fig14c_table = create_comparison_table(fig14c_table_data, "Proficiency")


    else:
        # NOTE: This should never ever happen. So yeah.
        fig14c_chart = no_data_fig_label("Comparison: Current Year ELA Proficiency",200)
        fig14c_table = no_data_table(["Proficiency"])

    fig14c = combine_barchart_and_table(fig14c_chart,fig14c_table)

    #### Current Year Math Proficiency Compared to Similar Schools (1.4.d) #
    category = "School Total|Math Proficient %"

    if category in display_academic_data.columns:

        fig14d_k8_data = display_academic_data[info_categories + [category]].copy()

        # fig14d_k8_school_data.loc[len(fig14d_k8_school_data.index)] = \
        #     [corp_name, "3","8",clean_corp_data[clean_corp_data['Category'] == category][string_year].values[0]]

        # Get comparable school values for the specific category
        # fig14d_comp_data = comparison_schools[info_categories + [category]]

        # fig14d_all_data = pd.concat([fig14d_k8_school_data,fig14d_comp_data])

        fig14d_table_data = fig14d_k8_data.copy()

        fig14d_k8_data[category] = pd.to_numeric(fig14d_k8_data[category])

        fig14d_chart = make_bar_chart(fig14d_k8_data, category, "Comparison: Current Year Math Proficiency")

        fig14d_table_data["School Name"] = create_school_label(fig14d_table_data)
        
        fig14d_table_data = fig14d_table_data[["School Name", category]]
        fig14d_table_data = fig14d_table_data.reset_index(drop=True)

        fig14d_table = create_comparison_table(fig14d_table_data, "Proficiency")
    
    else:
        fig14d_chart = no_data_fig_label("Comparison: Current Year Math Proficiency",200)
        fig14d_table = no_data_table(["Proficiency"])

    fig14d = combine_barchart_and_table(fig14d_chart,fig14d_table)

    #### Current Year IREAD Proficiency Compared to Similar Schools #
    category = "IREAD Proficient %"

    if category in display_academic_data.columns:

        fig_iread_data = display_academic_data[info_categories + [category]].copy()

        # fig_iread_k8_school_data.loc[len(fig_iread_k8_school_data.index)] = \
        #     [corp_name, "3","8",clean_corp_data[clean_corp_data['Category'] == category][string_year].values[0]]

        # fig_iread_comp_data = comparison_schools[info_categories + [category]]
        
        # fig_iread_all_data = pd.concat([fig_iread_k8_school_data,fig_iread_comp_data])

        fig_iread_table_data = fig_iread_data.copy()

        fig_iread_data[category] = pd.to_numeric(fig_iread_data[category])

        fig_iread_chart = make_bar_chart(fig_iread_data,category, "Comparison: Current Year IREAD Proficiency")

        fig_iread_table_data["School Name"] = create_school_label(fig_iread_table_data)

        fig_iread_table_data = fig_iread_table_data[["School Name", category]]
        fig_iread_table_data = fig_iread_table_data.reset_index(drop=True)

        fig_iread_table = create_comparison_table(fig_iread_table_data, "Proficiency")

    else:
        fig_iread_chart = no_data_fig_label("Comparison: Current Year IREAD Proficiency",200)
        fig_iread_table = no_data_table(["Proficiency"])

    fig_iread = combine_barchart_and_table(fig_iread_chart,fig_iread_table)

    # ELA Proficiency by Ethnicity Compared to Similar Schools (1.6.a.1)
    headers_16a1 = []
    for e in ethnicity:
        headers_16a1.append(e + "|" + "ELA Proficient %")

    categories_16a1 =  info_categories + headers_16a1

    # filter dataframe by categories
    fig16a1_k8_data = display_academic_data.loc[:, (display_academic_data.columns.isin(categories_16a1))]

    if len(fig16a1_k8_data.columns) > 3:
        
        fig16a1_final_data, fig16a1_category_string, fig16a1_school_string = \
            identify_missing_categories(fig16a1_k8_data, headers_16a1)
        
        fig16a1_label = create_chart_label(fig16a1_final_data)
        fig16a1_chart = make_group_bar_chart(fig16a1_final_data, fig16a1_label)
        fig16a1_table_data = combine_school_name_and_grade_levels(fig16a1_final_data)
        fig16a1_table = create_comparison_table(fig16a1_table_data, "")

        fig16a1 = combine_group_barchart_and_table(fig16a1_chart,fig16a1_table,fig16a1_category_string,fig16a1_school_string)
        
        fig16a1_container = {"display": "block"}
    
    else:
        fig16a1 = no_data_fig_label("Comparison: ELA Proficiency by Ethnicity", 200)             
        fig16a1_container = {"display": "none"}

    # Math Proficiency by Ethnicity Compared to Similar Schools (1.6.b.1)
    headers_16b1 = []
    for e in ethnicity:
        headers_16b1.append(e + "|" + "Math Proficient %")

    categories_16b1 =  info_categories + headers_16b1

    fig16b1_k8_school_data = display_academic_data.loc[:, (display_academic_data.columns.isin(categories_16b1))]

    if len(fig16b1_k8_school_data.columns) > 3:
        
        fig16b1_final_data, fig16b1_category_string, fig16b1_school_string = \
            identify_missing_categories(fig16b1_k8_school_data, headers_16b1)
        fig16b1_label = create_chart_label(fig16b1_final_data)
        fig16b1_chart = make_group_bar_chart(fig16b1_final_data, fig16b1_label)
        fig16b1_table_data = combine_school_name_and_grade_levels(fig16b1_final_data)
        fig16b1_table = create_comparison_table(fig16b1_table_data,"")

        fig16b1 = combine_group_barchart_and_table(fig16b1_chart,fig16b1_table,fig16b1_category_string,fig16b1_school_string)

        fig16b1_container = {"display": "block"}
    
    else:
        fig16b1 = no_data_fig_label("Comparison: Math Proficiency by Ethnicity", 200)
    
        fig16b1_container = {"display": "none"}

    # ELA Proficiency by Subgroup Compared to Similar Schools (1.6.a.2)
    headers_16a2 = []
    for s in subgroup:
        headers_16a2.append(s + "|" + "ELA Proficient %")
    
    categories_16a2 =  info_categories + headers_16a2

    fig16a2_k8_school_data = display_academic_data.loc[:, (display_academic_data.columns.isin(categories_16a2))]

    if len(fig16a2_k8_school_data.columns) > 3:

        fig16a2_final_data, fig16a2_category_string, fig16a2_school_string = \
            identify_missing_categories(fig16a2_k8_school_data, headers_16a2)
        fig16a2_label = create_chart_label(fig16a2_final_data)
        fig16a2_chart = make_group_bar_chart(fig16a2_final_data, fig16a2_label)
        fig16a2_table_data = combine_school_name_and_grade_levels(fig16a2_final_data)
        fig16a2_table = create_comparison_table(fig16a2_table_data,"")
        
        fig16a2 = combine_group_barchart_and_table(fig16a2_chart, fig16a2_table,fig16a2_category_string,fig16a2_school_string)
        fig16a2_container = {"display": "block"}
    
    else:
        fig16a2 = no_data_fig_label("Comparison: ELA Proficiency by Subgroup", 200)                
        fig16a2_container = {"display": "none"}

    # Math Proficiency by Subgroup Compared to Similar Schools (1.6.b.2)
    headers_16b2 = []
    for s in subgroup:
        headers_16b2.append(s + "|" + "Math Proficient %")

    categories_16b2 =  info_categories + headers_16b2

    fig16b2_k8_school_data = display_academic_data.loc[:, (display_academic_data.columns.isin(categories_16b2))]

    if len(fig16b2_k8_school_data.columns) > 3:

        fig16b2_final_data, fig16b2_category_string, fig16b2_school_string = \
            identify_missing_categories(fig16b2_k8_school_data, headers_16b2)
        fig16b2_label = create_chart_label(fig16b2_final_data)
        fig16b2_chart = make_group_bar_chart(fig16b2_final_data, fig16b2_label)
        fig16b2_table_data = combine_school_name_and_grade_levels(fig16b2_final_data)
        fig16b2_table = create_comparison_table(fig16b2_table_data,"")

        fig16b2 = combine_group_barchart_and_table(fig16b2_chart, fig16b2_table,fig16b2_category_string,fig16b2_school_string)
        fig16b2_container = {"display": "block"}

    
    else:
        fig16b2 = no_data_fig_label("Comparison: Math Proficiency by Subgroup", 200)            
        fig16b2_container = {"display": "none"}

    return (
        fig14c, fig14d, fig_iread, fig16a1, fig16a1_container, fig16b1, fig16b1_container, fig16a2,
        fig16a2_container, fig16b2, fig16b2_container, academic_analysis_main_container,
        academic_analysis_empty_container, no_data_to_display
    )
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
                                    placeholder="Select Year",                                    
                                ),
                            ],
                            className="pretty_container three columns",
                        ),                        
                        html.Div(
                            [
                                dcc.Dropdown(
                                    id="corporation-dropdown",
                                    style={
                                        "fontFamily": "Jost, sans-serif",
                                        'color': 'steelblue',
                                    },
                                    multi = True,
                                    clearable = True,
                                    className="school_dash_control",
                                    placeholder="Select School Corporation(s)",
                                ),
                            ],
                            className="pretty_container five columns",
                        ),
                        html.Div(
                            [
                                dcc.Dropdown(
                                    id="school-dropdown",
                                    style={
                                        "fontFamily": "Jost, sans-serif",
                                        'color': 'steelblue',
                                    },
                                    multi = True,
                                    clearable = True,
                                    className="school_dash_control",
                                    placeholder="Select School(s)",
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
                    # html.Div(
                    #     [
                    #         html.Div(
                    #             [
                    #                 html.Div(subnav_academic(),className="tabs"),
                    #             ],
                    #             className="bare_container_center twelve columns"
                    #         ),
                    #     ],
                    #     className="row"
                    # ),
                    html.Div(
                        [
                            # NOTE: This is an awkward workaround. Want a loading spinner on load, but for it not
                            # to trigger when comparison dropdown callback is triggered (which would happen if
                            # Loading wraps the entire page). So we just wrap the first 6 figs, so loading shows
                            # on initial load, but not on comparison dropdown use.         

                            html.Div(id="fig14c", children=[]),
                            html.Div(id="fig14d", children=[]),
                            html.Div(id="fig-iread", children=[]),
                            html.Div(
                                [
                                    html.Div(id="fig16a1"),
                                ],
                                id = "fig16a1-container",
                                style= {"display": "none"},
                            ),
                            html.Div([
                                    html.Div(id="fig16b1"),
                                ],
                                id = "fig16b1-container",
                                style= {"display": "none"},
                            ),
                            html.Div(
                                [      
                            html.Div(id="fig16a2"),
                                ],
                                id = "fig16a2-container",
                                style= {"display": "none"},
                            ),                                 
                            html.Div(
                                [                        
                                    html.Div(id="fig16b2"),
                                ],
                                id = "fig16b2-container",
                                style= {"display": "none"},
                            ),
                        ],
                        id = "academic-analysis-main-container",
                        style= {"display": "none"}, 
                    ),
                    html.Div(
                        [
                            html.Div(id="academic-analysis-no-data"),
                        ],
                        id = "academic-analysis-empty-container",
                    ),          
                ],
                id="mainContainer"
            ) 
            ],
        )
    ],
)

app.layout = layout # testing layout as a function - not sure its faster

if __name__ == "__main__":
    app.run_server(debug=True)
# #    application.run(host='0.0.0.0', port='8080')