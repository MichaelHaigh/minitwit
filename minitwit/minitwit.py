#!/usr/local/bin/python
"""
    MiniTwit
    ~~~~~~~~

    A microblogging application written with Flask and sqlite3.

    :copyright: (c) 2010 by the Pallets team.
    :license: BSD, see LICENSE for more details.
"""

import os
import time

from hashlib import md5
from datetime import datetime
from flask import Flask, request, session, url_for, redirect
from flask import render_template, abort, g, flash
from werkzeug.security import check_password_hash, generate_password_hash
import sqlalchemy as db
from sqlalchemy.sql import text

# ======================================================================
# constants

PER_PAGE = 30
DEBUG = True

DB_STASH = "db"

SECRET_KEY = "development key"

# ======================================================================
# create our little application :)

app = Flask(__name__)  # pylint: disable=invalid-name

# The only local config param we actually read is DEBUG
app.config.from_object(__name__)

# Read config settings from the file specified by this env var, if it is defined.
app.config.from_envvar("MINITWIT_SETTINGS", silent=True)
app.config["MYSQL_DATABASE_USER"] = "root"
app.config["MYSQL_DATABASE_PASSWORD"] = os.getenv("db_root_password")
app.config["MYSQL_DATABASE_DB"] = os.getenv("db_name")
app.config["MYSQL_DATABASE_HOST"] = os.getenv("db_host")
app.config["MYSQL_DATABASE_PORT"] = 3306


endpoint = app.config.get("MYSQL_DATABASE_HOST")
name = app.config.get("MYSQL_DATABASE_DB")
username = app.config.get("MYSQL_DATABASE_USER")
password = app.config.get("MYSQL_DATABASE_PASSWORD")

db_url = "mysql://{}:{}@{}:3306/{}".format(username, password, endpoint, name)

app.logger.info(  # pylint: disable=no-member
    "db_type=%s endpoint=%s db=%s username=%s",
    "mysql",
    endpoint,
    name,
    username,
)

DB_ENGINE = db.create_engine(db_url)


def get_db():
    """Opens a new database connection if there is none yet for the
    current request.
    """
    if DB_STASH not in g:
        g.db = DB_ENGINE.connect()  # pylint: disable=assigning-non-slot

    return g.db


@app.teardown_appcontext
def close_database(_exception):
    """Closes the database again at the end of the request."""
    the_db = g.pop(DB_STASH, None)

    if the_db is not None:
        the_db.close()


def init_db():
    """Initializes the database."""
    the_db = get_db()

    schema_file = "schema.sql"

    with app.open_resource(schema_file, mode="r") as fil:
        queries_string = fil.read()
        queries = queries_string.split(";")
        for query in queries:
            if len(query.strip()) > 0:
                the_db.execute(query.strip() + ";")


@app.cli.command("initdb")
def initdb_command():
    """Creates the database tables."""
    init_db()
    print("Initialized the database.")


def query_db(query, args=None, one=False):
    """Queries the database and returns a list of dictionaries."""

    values = list(exec_db(query, args))
    return (values[0] if values else None) if one else values


def exec_db(query, args=None):
    """Queries the database and return the result as is."""

    if args is None:
        args = dict()

    stmt = text(query)
    return get_db().execute(stmt, **args)


def get_user_id(username):
    """Convenience method to look up the id for a username."""
    value = query_db(
        "select user_id from user where username = :username", {"username": username}, one=True
    )
    return value[0] if value else None  # pylint: disable=unsubscriptable-object


def format_datetime(timestamp):
    """Format a timestamp for display."""
    return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d @ %H:%M")


def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    return "https://www.gravatar.com/avatar/%s?d=identicon&s=%d" % (
        md5(email.strip().lower().encode("utf-8")).hexdigest(),
        size,
    )


@app.before_request
def before_request():
    """Do before-request operations"""
    g.user = None  # pylint: disable=assigning-non-slot
    if "user_id" in session:
        g.user = query_db(
            "select * from user where user_id = :userid",  # pylint: disable=assigning-non-slot
            {"userid": session["user_id"]},
            one=True,
        )


@app.route("/")
def timeline():
    """Shows a users timeline or if no user is logged in it will
    redirect to the public timeline.  This timeline shows the user's
    messages as well as all the messages of followed users.
    """
    if not g.user:
        return redirect(url_for("public_timeline"))
    return render_template(
        "timeline.html",
        messages=query_db(
            """
        select message.*, user.* from message, user
        where message.author_id = user.user_id and (
            user.user_id = :userid or
            user.user_id in (select whom_id from follower
                                    where who_id = :whoid))
        order by message.pub_date desc limit :limit""",
            {"userid": session["user_id"], "whoid": session["user_id"], "limit": PER_PAGE},
        ),
    )


@app.route("/public")
def public_timeline():
    """Displays the latest messages of all users."""
    return render_template(
        "timeline.html",
        messages=query_db(
            """
        select message.*, user.* from message, user
        where message.author_id = user.user_id
        order by message.pub_date desc limit :limit""",
            {"limit": PER_PAGE},
        ),
    )


@app.route("/<username>")
def user_timeline(username):
    """Display's a users tweets."""
    profile_user = query_db(
        "select * from user where username = :username", {"username": username}, one=True
    )
    if profile_user is None:
        abort(404)
    followed = False
    if g.user:
        followed = (
            query_db(
                """select 1 from follower where
            follower.who_id = :whoid and follower.whom_id = :whomid""",
                {
                    "whoid": session["user_id"],
                    "whomid": profile_user["user_id"],
                },  # pylint: disable=unsubscriptable-object
                one=True,
            )
            is not None
        )
    return render_template(
        "timeline.html",
        messages=query_db(
            """select message.*, user.* from message, user where
            user.user_id = message.author_id and user.user_id = :userid
            order by message.pub_date desc limit :limit""",
            {"userid": profile_user["user_id"], "limit": PER_PAGE},
        ),  # pylint: disable=unsubscriptable-object
        followed=followed,
        profile_user=profile_user,
    )


@app.route("/<username>/follow")
def follow_user(username):
    """Adds the current user as follower of the given user."""
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)

    exec_db(
        "insert into follower (who_id, whom_id) values (:whoid, :whomid)",
        dict(whoid=session["user_id"], whomid=whom_id),
    )
    # db.commit()
    init_db()
    flash('You are now following "%s"' % username)
    return redirect(url_for("user_timeline", username=username))


@app.route("/<username>/unfollow")
def unfollow_user(username):
    """Removes the current user as follower of the given user."""
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)

    exec_db(
        "delete from follower where who_id=:whoid and whom_id=:whomid",
        dict(whoid=session["user_id"], whomid=whom_id),
    )

    flash('You are no longer following "%s"' % username)
    return redirect(url_for("user_timeline", username=username))


@app.route("/add_message", methods=["POST"])
def add_message():
    """Registers a new message for the user."""
    if "user_id" not in session:
        abort(401)
    if request.form["text"]:
        exec_db(
            """insert into message (author_id, text, pub_date)
            values (:authorid, :text, :pubdate)""",
            dict(authorid=session["user_id"], text=request.form["text"], pubdate=int(time.time())),
        )

        flash("Your message was recorded")
    return redirect(url_for("timeline"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Logs the user in."""
    if g.user:
        return redirect(url_for("timeline"))
    error = None
    if request.method == "POST":
        user = query_db(
            """select * from user where
            username = :username""",
            {"username": request.form["username"]},
            one=True,
        )
        if user is None:
            error = "Invalid username"
        elif not check_password_hash(
            user["pw_hash"], request.form["password"]  # pylint: disable=unsubscriptable-object
        ):
            error = "Invalid password"
        else:
            flash("You were logged in")
            session["user_id"] = user["user_id"]  # pylint: disable=unsubscriptable-object
            return redirect(url_for("timeline"))
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Registers the user."""
    if g.user:
        return redirect(url_for("timeline"))
    error = None
    if request.method == "POST":
        if not request.form["username"]:
            error = "You have to enter a username"
        elif not request.form["email"] or "@" not in request.form["email"]:
            error = "You have to enter a valid email address"
        elif not request.form["password"]:
            error = "You have to enter a password"
        elif request.form["password"] != request.form["password2"]:
            error = "The two passwords do not match"
        elif get_user_id(request.form["username"]) is not None:
            error = "The username is already taken"
        else:
            exec_db(
                """insert into user (
                username, email, pw_hash) values (:username, :email, :pwhash)""",
                dict(
                    username=request.form["username"],
                    email=request.form["email"],
                    pwhash=generate_password_hash(request.form["password"]),
                ),
            )

            flash("You were successfully registered and can login now")
            return redirect(url_for("login"))
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    """Logs the user out."""
    flash("You were logged out")
    session.pop("user_id", None)
    return redirect(url_for("public_timeline"))


# add some filters to jinja
# pylint: disable=no-member
app.jinja_env.filters["datetimeformat"] = format_datetime
app.jinja_env.filters["gravatar"] = gravatar_url
# pylint: enable=no-member
