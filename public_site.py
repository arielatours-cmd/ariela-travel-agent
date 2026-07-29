from flask import Blueprint, render_template

site = Blueprint("site", __name__)


@site.get("/")
def home():
    return render_template("home.html")


@site.get("/about")
def about():
    return render_template("about.html")
