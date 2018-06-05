from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from tempfile import gettempdir
import collections
from helpers import *

""" 
As cute as the cat from apology is, it would be alot more convenient for the user if the apology
message were displayed on the same page that they were interacting with. So I modified
layout.html to have take a 'msg' variable, which can be passed via render_template and am bpyassing
the apology function completely.
"""

# configure application
app = Flask(__name__)

# ensure responses aren't cached
if app.config["DEBUG"]:
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

# custom filter
app.jinja_env.filters["usd"] = usd

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = gettempdir()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Since I load portfolio in two places (index, and sell page) it made sense to make this its own function.
def get_portfolio():
    # This just makes sure that any time get_portfolio is run, any stocks with 0 shares after a sale are removed. 
    db.execute("DELETE FROM portfolios WHERE shares=0")
    portfolio = db.execute("SELECT * FROM portfolios WHERE user_id=:user_id", user_id=session["user_id"])
    # Since get_portfolio returns a list of dictionaries, we can just iterate over each dictionary and add current price and values.
    total_value = 0
    for row in portfolio:
        row["c_price"] = "$" + str(lookup(row["stocks"])["price"])
        c_value = float(lookup(row["stocks"])["price"]) * row["shares"]
        row["c_value"] = "$" + "{0:.2f}".format(c_value)
        total_value += c_value
    cash = db.execute("SELECT cash FROM users WHERE id=:id", id = session["user_id"])[0]["cash"]
    portfolio.append({"stocks": "CASH", "c_value": "$" + str("{0:.2f}".format(cash))})
    portfolio.append({"stocks": "GRAND TOTAL", "c_value":  "$" + str("{0:.2f}".format(total_value + cash))})
    return portfolio

# Same idea here, I use get_shares in multiple places so made a function for it.
def get_shares(stock):
    try:
        owned = db.execute("SELECT shares from portfolios WHERE user_id=:user_id AND stocks=:stock",
            user_id=session["user_id"], stock=stock)[0]["shares"]
    except:
        owned = 0
    # Add that to number purchased and return it
    return int(request.form.get("quantity")) + owned

@app.route("/", methods=["GET"])
@login_required
def index():
    return render_template("index.html", portfolio = get_portfolio())

@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock."""
    if request.method == "POST":
        qt = lookup(request.form.get("stock"))
        # If qt is 'none' then return buy page with msg at top.
        if not qt:
            return render_template("buy.html", msg="Invalid stock symbol.")
        # Or if the user didn't supply a quantity or entered something less than 1, complain again.
        elif not request.form.get("quantity") or int(request.form.get("quantity")) < 1:
            return render_template("buy.html", msg="Invalid quantity.")
        # Otherwise everything is okie dokie (almost...)
        else:
            # Find out how much cash the user has.
            cash = db.execute("SELECT cash FROM users WHERE id=:user_id", user_id=session["user_id"])[0]["cash"]
            # Figure out what they want to buy will cost in total.
            cost = qt["price"] * int(request.form.get("quantity"))
            # If they can't afford it, tell them so.
            if cost > cash:
                return render_template("buy.html", msg = "Insufficient funds.")
            # Okay, NOW everything is okie dokie.
            else:
                '''
                This variable is a concatenation of the user_id and stock to create a unique ID that I can query on. I'm doing this
                to enforce that every user can only have a maximum instance of one stock symbol in their portfolio. I originally
                tried to create dynamically named portfolio tables upon registration for each user. Couldn't get that to work
                so had to put all users in same portfolio table. This allows me to interact with a specific users portfolio
                without screwing up another users data.
                '''
                user_stock_id = str(session["user_id"])  + qt["symbol"]
                # Inserts transaction into transaction table
                db.execute("INSERT into transactions(user_id, type, stock, quantity, unit_price) VALUES(:user_id, 0, :stock, :quantity, :unit_price)",
                            user_id=session["user_id"], unit_price = qt["price"], stock=qt["symbol"], quantity=request.form.get("quantity"))
                # Checks to see if the user_stock_id is NOT in the table because in that case we only want to do an insert.
                if not db.execute("SELECT user_stock_id from portfolios where user_stock_id=:user_stock_id", user_stock_id = user_stock_id):
                    db.execute("INSERT INTO portfolios(user_id, stocks, user_stock_id) VALUES(:user_id, :stock, :user_stock_id)",
                                user_id=session["user_id"], stock=qt["symbol"], user_stock_id=user_stock_id)
                # Otherwise, the user_stock_id is in table and we need to update it. Note we can't update quantity yet.
                else:
                    db.execute("UPDATE portfolios SET user_id=:user_id, stocks=:stock, user_stock_id=:user_stock_id",
                            user_id=session["user_id"], stock=qt["symbol"], user_stock_id=str(session["user_id"])  + qt["symbol"])
                # Now that we know record is in DB either thru update or insert, we need to update shares.
                shares = get_shares(qt["symbol"])
                # And update shares in table to new quantity.
                db.execute("UPDATE portfolios set shares=:shares WHERE user_id=:user_id AND stocks=:stock",
                            shares=shares, user_id=session["user_id"], stock=qt["symbol"])
                # Figure out the users remaining balance so we can report it as a msg.            
                balance = cash - cost
                msg = "Transaction Complete!\n Remaining Balance: $" + "{0:.2f}".format(balance)
                # Lastly, subtract the cash from the user table and render template.
                db.execute("UPDATE users set cash=:remaining WHERE id=:id", remaining = balance, id=session["user_id"])
                return render_template("transaction.html", name = qt["name"], quantity = request.form.get("quantity"),
                                        price = "{0:.2f}".format(qt["price"]), msg = msg,
                                        symbol = qt["symbol"], total = "{0:.2f}".format(cost), type="Purchase")
    # Request method was get, just load default buy page
    else:
        return render_template("buy.html")    

@app.route("/history")
@login_required
def history():
    """Show history of transactions."""
    # Get the user's transaction history.
    history = db.execute("SELECT * FROM transactions where user_id=:user_id", user_id=session["user_id"])
    m = ""
    
    #convert the type int to text (I store purchases as 0 and sales as 1 in DB)
    for row in history:
        if row["type"] == 0:
            row["type"] = "PURCHASE"
        else:
            row["type"] = "SALE"
    return render_template("history.html", history = history, msg = m)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in."""

    # forget any user_id
    session.clear()

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # ensure username was submitted
        if not request.form.get("username"):
            return render_template("login.html", msg="Please provide username.")

        # ensure password was submitted
        elif not request.form.get("password"):
            return render_template("login.html", msg="Please enter password.")

        # query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))

        # ensure username exists and password is correct
        if len(rows) != 1 or not pwd_context.verify(request.form.get("password"), rows[0]["hash"]):
            return render_template("login.html", msg="Invalid username and/or password.")

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # redirect user to home page
        return redirect(url_for("index"))

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out."""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect(url_for("login"))

@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    # user posted the form, so lets process it.
    if request.method == "POST":
        qt = lookup(request.form.get("stock"))
        # If the form returned none, it means user didn't enter a valid symbol.
        if not qt:
            return render_template("quote.html", msg="Invalid stock symbol.")
        # If they did, give call dictionary keys into render_template to give a quote
        else:
            return render_template("quoted.html", name = qt["name"], price = qt["price"], symbol = qt["symbol"])
    # request was get, so just load default quote page.
    else:
        return render_template("quote.html")
    
@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user."""
    # ensure username was submitted
    if request.method == "POST":
        if not request.form.get("create_username"):
            return render_template("register.html", msg="Please create username.")
        
        # ensure password was submitted
        elif not request.form.get("create_password"):
            return render_template("register.html", msg="Please create password.")
        
        # ensure that confirm_password was submitted
        elif not request.form.get("confirm_password"):
            return register_template("register.html", msg="Please confirm password.")
        
        # ensures both password fields match.
        elif request.form.get("create_password") != request.form.get("confirm_password"):
            return register_template("register.html", msg="Both password fields must match.")
            
        # everything looks okay, so create the user/password in db
        else:
            # register user in db with hashed password
            user = request.form.get("create_username")
            hash = pwd_context.encrypt(request.form.get("create_password"))
            result = db.execute("INSERT into users(username, hash) VALUES(:username, :hash)", 
                                username = user,
                                hash = hash)
            if not result:
                # if result returns None, it means the INSERT statement failed so we say user name already exists.
                return render_template("register.html", msg="Username already exists.")
            else:
                # Otherwise insertion worked and we can set session_id to the current user.
                session["user_id"] = db.execute("SELECT id from users WHERE username=:username",
                                                username = user)
                '''
                So this is where i cry 'mia culpa' because I can't figure out the problem here. I know we were instructed to have
                user redirected to index after registering, but for some reason with my implementation this causes all sorts of
                'index out of range' errors. I was able to debug enough to determine that the print statement below returns
                an empty list when I expected to see '10,000'. I can't for the life of me figure out why, since the DB is setting
                this field, it ought to populate. The only way around this problem has been for user to log in manually, so
                that's why I redirect to login now.
                '''
                # print(db.execute("SELECT cash FROM users WHERE id=:id", id = session["user_id"])
                # return redirect(url_for("index"))
                return redirect(url_for("login"))
    # renders the template if method is get.        
    else:
        return render_template("register.html")

@app.route("/change", methods=["GET", "POST"])
@login_required
def change():
    # User posted the form to change their password...
    if request.method == "POST":
        # so let's make sure they filled out the original password field...
        if not request.form.get("orig_pwd"):
            return render_template("change.html", msg="Original password required.")
        # and the field for the new password...
        elif not request.form.get("ch_pwd"):
            return render_template("change.html", msg="New password required.")
        # and that they typed it in again
        elif not request.form.get("cnf_pwd"):
            return render_template("change.html", msg="New password confirmation required.")
        # and that the new field and confirmation field contents match
        elif request.form.get("ch_pwd") != request.form.get("cnf_pwd"):
            return render_template("change.html", msg="New password does not match confirmation password.")
        # and if they did all that right, we can change the pw by...
        else:
            # First getting the stored pw as a hash...
            db_hash = db.execute("SELECT hash FROM users WHERE id=:user_id", 
                                                       user_id=session["user_id"])[0]["hash"]
            # And making a hash out of what the user said was the stored password...
            orig_hash = pwd_context.encrypt(request.form.get("orig_pwd"))
            # And making sure that both match (thx to https://pythonhosted.org/passlib/narr/quickstart.html)
            if not pwd_context.verify(request.form.get("orig_pwd"), db_hash):
                return render_template("change.html", msg="Original password does not match our records. Try again.")
            # and if they do...
            else:
                # hash the new password...
                new_hash = pwd_context.encrypt(request.form.get("ch_pwd"))
                # and update the DB
                result = db.execute("UPDATE users SET hash=:hash WHERE id=:user_id",
                                    user_id = session["user_id"],
                                    hash = new_hash)
                # and make sure the execute statement worked 
                if not result:
                    return render_template("change.html", msg="Password change failed.")
                # and render the template with a success message.
                else:
                    return render_template("change.html", msg="Password changed.")
    else:
        return render_template("change.html")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""
    # User posted the form to sell stock...
    if request.method=="POST":
        # Make sure they enter a stock code...
        if not request.form.get("stock"):
            return render_template("sell.html", portfolio = get_portfolio(), msg ="Please enter a stock to sell.")
        # And a quantity greater than zero...
        elif not request.form.get("quantity") or int(request.form.get("quantity")) < 1:
            return render_template("buy.html", msg="Invalid quantity.")    
        # Everything looks (almost) ok...
        else:
            # So lets iterate through their portfolio..
            for row in get_portfolio():
                # And if we find the stock they want to sell in one of the portfolio dictionaries...
                if row["stocks"] == request.form.get("stock"):
                    # and they own shares equal to or greater than the number they want to sell...
                    if int(request.form.get("quantity")) <= row["shares"]:
                        #record sales transaction in transactions table
                        db.execute("INSERT into transactions(user_id, type, stock, quantity, unit_price) VALUES(:user_id, 1, :stock, :quantity, :unit_price)", 
                            user_id=session["user_id"], unit_price = row["c_price"], stock=row["stocks"], quantity=request.form.get("quantity"))
                        #add cash to users table
                        cash = db.execute("SELECT cash FROM users WHERE id=:user_id", user_id=session["user_id"])[0]["cash"]
                        sale = int(request.form.get("quantity")) * float(row["c_price"].lstrip("$"))
                        db.execute("UPDATE users set cash=:remaining WHERE id=:id", remaining = cash + sale, id=session["user_id"])
                        # And update their portfolio to reflect that they sold some stocks.
                        user_stock_id = str(session["user_id"]) + row["stocks"]
                        holding = db.execute("SELECT shares FROM portfolios WHERE user_stock_id=:user_stock_id",
                                             user_stock_id = user_stock_id)[0]["shares"] - int(request.form.get("quantity"))
                        db.execute("UPDATE portfolios set shares=:shares WHERE user_stock_id=:user_stock_id",
                                    shares = holding, user_stock_id = user_stock_id)
                    else:
                        return render_template("sell.html", portfolio=get_portfolio(), msg="Quantity specified exceeds shares held.")
                    
            return render_template("sell.html", portfolio = get_portfolio())
    else:
        return render_template("sell.html", portfolio = get_portfolio())
