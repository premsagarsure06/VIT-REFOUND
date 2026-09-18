from flask import Flask, request, redirect, session, send_from_directory
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import difflib
import random
import smtplib
import os
from email.message import EmailMessage
from datetime import datetime

app = Flask(__name__)
@app.route("/google18764604b74a2c6d.html")
def google_verification():
    return send_from_directory(
        ".",
        "google18764604b74a2c6d.html"
    )
@app.route("/sitemap.xml")
def sitemap():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://vit-refound.vercel.app/</loc>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>
"""
    return xml, 200, {"Content-Type": "application/xml"}
app.secret_key =os.environ.get("SECRET_KEY")

# ==================================================
# OTP EMAIL SETTINGS
# ==================================================
SMTP_EMAIL =os.environ.get("SMTP_EMAIL")
SMTP_APP_PASSWORD =os.environ.get("SMTP_APP_PASSWORD")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 5


# ==================================================
# DATABASE
# ==================================================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured in Vercel.")
    return psycopg2.connect(DATABASE_URL, sslmode="require", cursor_factory=RealDictCursor)


def create_database():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            date_found TEXT NOT NULL,
            public_description TEXT,
            verification_details TEXT NOT NULL,
            finder_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Available',
            FOREIGN KEY (finder_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            claimant_id INTEGER NOT NULL,
            verified INTEGER DEFAULT 0,
            received INTEGER DEFAULT 0,
            FOREIGN KEY (item_id) REFERENCES items(id),
            FOREIGN KEY (claimant_id) REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()


create_database()


# ==================================================
# VIT-AP EMAIL VALIDATION
# ==================================================
def is_valid_vitap_email(email):
    email = email.lower().strip()
    return "vitapstudent" in email or email.endswith("@vitap.ac.in")


# ==================================================
# TEXT HELPERS
# ==================================================
def normalize_text(text):
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact_text(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def tokenize(text):
    return re.findall(r"[a-z0-9]+", normalize_text(text))


# ==================================================
# EXPANDED SMART ITEM VOCABULARY
# ==================================================
RELATED_WORDS = {
    "keychain": [
        "keychain", "key chain", "keys", "key ring", "keyring",
        "key holder", "key holder ring"
    ],
    "phone": [
        "phone", "mobile", "cellphone", "cell phone",
        "smartphone", "smart phone", "iphone", "android",
        "mobile phone", "handset"
    ],
    "laptop": [
        "laptop", "computer", "notebook", "macbook",
        "personal computer", "portable computer"
    ],
    "earphones": [
        "earphones", "ear phones", "headphones", "headset",
        "earbuds", "airpods", "bluetooth earphones",
        "bluetooth headphones"
    ],
    "wallet": [
        "wallet", "purse", "money wallet", "card holder",
        "cardholder", "pocket wallet"
    ],
    "bag": [
        "bag", "bags", "backpack", "school bag",
        "college bag", "rucksack", "book bag"
    ],
    "idcard": [
        "id card", "idcard", "identity card",
        "college id", "student id", "student card"
    ],
    "charger": [
        "charger", "mobile charger", "phone charger",
        "charging cable", "power adapter", "adapter",
        "charging adapter", "type c charger"
    ],
    "bottle": [
        "bottle", "water bottle", "waterbottle",
        "flask", "water flask", "sipper"
    ],
    "watch": [
        "watch", "wrist watch", "smartwatch",
        "smart watch", "digital watch"
    ],
    "keys": [
        "key", "keys", "door key", "room key",
        "hostel key", "bike key", "car key"
    ],
    "umbrella": [
        "umbrella", "rain umbrella", "folding umbrella"
    ],
    "spectacles": [
        "spectacles", "spectacle", "glasses", "eyeglasses",
        "eye glasses", "specs"
    ],
    "calculator": [
        "calculator", "scientific calculator", "casio", "calc"
    ],
    "book": [
        "book", "textbook", "text book", "novel", "study book"
    ],
    "pen": [
        "pen", "ball pen", "ballpoint", "gel pen",
        "ink pen", "marker pen"
    ],
    "purse": [
        "purse", "hand purse", "small purse", "clutch"
    ],
    "usb": [
        "usb", "pendrive", "pen drive", "flash drive",
        "usb drive", "memory stick"
    ]
}


def get_standard_item(word):
    normalized_word = compact_text(word)

    for standard_name, variations in RELATED_WORDS.items():
        if normalized_word == compact_text(standard_name):
            return standard_name

        for variation in variations:
            if normalized_word == compact_text(variation):
                return standard_name

    return normalized_word


def expand_terms(text):
    words = tokenize(text)
    compact_full = compact_text(text)
    expanded = set(words)

    for word in words:
        standard = get_standard_item(word)
        if standard:
            expanded.add(standard)

    for standard_name, variations in RELATED_WORDS.items():
        forms = [standard_name] + variations
        compact_forms = [compact_text(x) for x in forms]

        if any(form in compact_full for form in compact_forms):
            expanded.add(standard_name)

    return expanded


# ==================================================
# ADVANCED SMART SEARCH MATCHING
# ==================================================
def smart_item_score(
    search_text,
    item_name,
    category="",
    location="",
    public_description=""
):
    """
    Smart matching score from 0 to 100.

    Uses:
    - exact match
    - no-space/spacing match
    - related words
    - synonyms
    - singular/plural
    - partial words
    - spelling similarity
    - category
    - location
    - public description
    """

    query = normalize_text(search_text)
    item = normalize_text(item_name)

    if not query:
        return 0

    query_compact = compact_text(query)
    item_compact = compact_text(item)

    score = 0

    # 1. Exact
    if query == item:
        score += 55

    # 2. Ignore spaces/special characters
    if query_compact == item_compact:
        score += 18

    # 3. Phrase containment
    if query in item:
        score += 28
    elif item in query:
        score += 18

    # 4. Related concepts
    query_concepts = expand_terms(query)
    item_concepts = expand_terms(item)
    common_concepts = query_concepts.intersection(item_concepts)

    if common_concepts:
        score += min(35, 20 + (len(common_concepts) - 1) * 7)

    # 5. Token overlap
    query_tokens = set(tokenize(query))
    item_tokens = set(tokenize(item))

    if query_tokens:
        common_tokens = query_tokens.intersection(item_tokens)
        score += (len(common_tokens) / len(query_tokens)) * 25

    # 6. Partial token matching
    partial_hits = 0

    for qword in query_tokens:
        for iword in item_tokens:
            if len(qword) >= 3 and len(iword) >= 3:
                if qword in iword or iword in qword:
                    partial_hits += 1
                    break

    if query_tokens:
        score += (partial_hits / len(query_tokens)) * 15

    # 7. Lower fuzzy threshold: old value was 0.70
    fuzzy = difflib.SequenceMatcher(
        None,
        query_compact,
        item_compact
    ).ratio()

    if fuzzy >= 0.45:
        score += fuzzy * 18

    # 8. Category
    category_concepts = expand_terms(category)

    if query_concepts.intersection(category_concepts):
        score += 8

    # 9. Location
    query_location_words = set(tokenize(query))
    location_words = set(tokenize(location))

    if query_location_words.intersection(location_words):
        score += 7

    # 10. Public description
    description_words = set(tokenize(public_description))

    if query_location_words.intersection(description_words):
        score += 6

    return min(100, round(score, 1))


def item_matches(
    search_text,
    item_name,
    category="",
    location="",
    public_description=""
):
    # Lower overall search acceptance than the previous system.
    return smart_item_score(
        search_text,
        item_name,
        category,
        location,
        public_description
    ) >= 28


# ==================================================
# VERIFICATION MATCHING
# ==================================================
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were",
    "and", "or", "with", "of", "in", "on", "at",
    "my", "this", "that", "it", "has", "have",
    "i", "me", "to", "for", "from", "there",
    "its", "very", "small", "large", "big", "little",
    "one", "item", "thing", "also", "inside", "near"
}


def get_keywords(text):
    words = tokenize(text)

    return {
        word
        for word in words
        if word not in STOP_WORDS and len(word) > 2
    }


def keyword_variants(word):
    variants = {word}

    standard = get_standard_item(word)
    variants.add(standard)

    if standard in RELATED_WORDS:
        for variation in RELATED_WORDS[standard]:
            variants.add(compact_text(variation))

    if word.endswith("s") and len(word) > 3:
        variants.add(word[:-1])
    else:
        variants.add(word + "s")

    return variants


def verification_match_score(finder_details, user_details):
    """
    IMPORTANT:
    The claimant can proceed when 50% or more of the
    meaningful finder verification details are supported.

    It is NOT exact matching.
    """

    finder_keywords = get_keywords(finder_details)
    user_keywords = get_keywords(user_details)

    if not finder_keywords or not user_keywords:
        return 0.0, set()

    matched_words = set()

    # Direct + synonym + singular/plural matching
    for finder_word in finder_keywords:
        finder_variants = keyword_variants(finder_word)

        for user_word in user_keywords:
            user_variants = keyword_variants(user_word)

            if finder_variants.intersection(user_variants):
                matched_words.add(finder_word)
                break

    # Spelling-error matching.
    # Lower than the old 0.70 level.
    for finder_word in finder_keywords:
        if finder_word in matched_words:
            continue

        best_ratio = 0

        for user_word in user_keywords:
            ratio = difflib.SequenceMatcher(
                None,
                compact_text(finder_word),
                compact_text(user_word)
            ).ratio()

            best_ratio = max(best_ratio, ratio)

        if best_ratio >= 0.55:
            matched_words.add(finder_word)

    # Phrase support
    finder_compact = compact_text(finder_details)
    user_compact = compact_text(user_details)

    if finder_compact and user_compact:
        if finder_compact in user_compact:
            matched_words.update(finder_keywords)

    matched_count = len(matched_words)
    total_count = len(finder_keywords)

    percentage = (matched_count / total_count) * 100

    return round(percentage, 1), matched_words


def verification_matches(finder_details, user_details):
    score, common_words = verification_match_score(
        finder_details,
        user_details
    )

    # USER REQUIREMENT: 50% is enough to claim.
    if score >= 50:
        return True, common_words, score

    return False, common_words, score


# ==================================================
# HTML PAGE
# ==================================================
def page(title, body):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>

        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f8f5f0;
                margin: 0;
                color: #222;
            }}

            .page {{
                max-width: 900px;
                margin: 30px auto;
                background: white;
                padding: 35px;
                border-radius: 18px;
                box-shadow: 0 8px 30px rgba(0,0,0,0.08);
            }}

            .logo {{
                display: block;
                width: 230px;
                max-width: 80%;
                margin: 0 auto 25px auto;
            }}

            h1 {{
                color: #8b0000;
                text-align: center;
            }}

            h2 {{
                color: #8b0000;
            }}

            input, select, textarea {{
                width: 100%;
                max-width: 600px;
                box-sizing: border-box;
                padding: 12px;
                margin-top: 7px;
                border: 1px solid #ccc;
                border-radius: 8px;
                font-size: 15px;
            }}

            textarea {{
                min-height: 130px;
            }}

            button {{
                background: #a40000;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
            }}

            button:hover {{
                background: #7d0000;
            }}

            a {{
                color: #8b0000;
                text-decoration: none;
                font-weight: bold;
            }}

            .error {{
                color: #b00020;
                background: #fff0f0;
                padding: 12px;
                border-radius: 8px;
            }}

            .success {{
                color: #176b35;
                background: #effaf2;
                padding: 12px;
                border-radius: 8px;
            }}

            .info {{
                background: #f5f5f5;
                padding: 18px;
                border-radius: 12px;
            }}

            .result {{
                border: 1px solid #ddd;
                padding: 18px;
                margin: 18px 0;
                border-radius: 12px;
                background: #fff;
            }}

            .match {{
                display: inline-block;
                background: #eef7ef;
                color: #176b35;
                padding: 7px 12px;
                border-radius: 20px;
                font-weight: bold;
            }}

            .returned {{
                color: #b00020;
                font-weight: bold;
            }}

            .center {{
                text-align: center;
            }}

            .small {{
                color: #666;
                font-size: 13px;
            }}
        </style>
    </head>

    <body>
        <div class="page">

            <img src="/static/vit_ap_logo.png"
               class="logo"
               alt="VIT-AP University">

            {body}

        </div>
    </body>
    </html>
    """


# ==================================================
# OTP EMAIL
# ==================================================
def send_otp_email(receiver_email, otp):

    # Local testing mode
    if (
        SMTP_EMAIL == "YOUR_EMAIL@gmail.com"
        or SMTP_APP_PASSWORD == "YOUR_16_DIGIT_APP_PASSWORD"
    ):
        print("=" * 55)
        print("VIT REFOUND PASSWORD RESET OTP")
        print("Email:", receiver_email)
        print("OTP:", otp)
        print("Valid for:", OTP_EXPIRY_MINUTES, "minutes")
        print("=" * 55)
        return True

    try:
        message = EmailMessage()

        message["Subject"] = "VIT REFOUND - Password Reset OTP"
        message["From"] = SMTP_EMAIL
        message["To"] = receiver_email

        message.set_content(
            f"""
VIT REFOUND - Password Reset

Your OTP is: {otp}

This OTP is valid for {OTP_EXPIRY_MINUTES} minutes.

If you did not request this password reset,
please ignore this email.
"""
        )

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.send_message(message)

        return True

    except Exception as error:
        print("OTP email error:", error)
        print("TEST OTP:", otp)
        return False


# ==================================================
# HOME
# ==================================================
@app.route("/")
def home():

    if "user_id" in session:
        return redirect("/dashboard")

    body = """
        <h1>🎒 VIT REFOUND</h1>

        <h2 class="center">
            Turning lost into found
        </h2>

        <p class="center">
            Find your lost belongings or report an item you found.
        </p>

        <div class="center">

            <a href="/register">
                <button>📝 Register</button>
            </a>

            <a href="/login">
                <button>🔐 Login</button>
            </a>

        </div>
    """

    return page("VIT REFOUND", body)


# ==================================================
# REGISTER
# ==================================================
@app.route("/register", methods=["GET", "POST"])
def register():

    error_message = ""

    if request.method == "POST":

        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not is_valid_vitap_email(email):

            error_message = """
            ❌ Please use a valid VIT-AP email.<br><br>
            Email must contain <b>vitapstudent</b>
            or end with <b>@vitap.ac.in</b>.
            """

        elif len(password) < 6:

            error_message = (
                "❌ Password must contain at least 6 characters."
            )

        else:

            try:

                connection = get_connection()
                cursor = connection.cursor()

                cursor.execute("""
                    INSERT INTO users (name, email, password)
                    VALUES (%s, %s, %s)
                """, (name, email, password))

                connection.commit()
                connection.close()

                return redirect("/login")

            except psycopg2.IntegrityError:

                error_message = (
                    "❌ This email is already registered!"
                )

    body = f"""
        <h1>📝 Create Your Account</h1>

        <form method="POST">

            <label>Name:</label><br>
            <input type="text"
                   name="name"
                   required>

            <br><br>

            <label>VIT-AP Email:</label><br>
            <input type="email"
                   name="email"
                   placeholder="Enter VIT-AP email"
                   required>

            <br><br>

            <label>Password:</label><br>
            <input type="password"
                   name="password"
                   minlength="6"
                   required>

            <br><br>

            <button type="submit">
                📝 Register
            </button>

        </form>

        <br>

        <p class="error">
            {error_message}
        </p>

        <a href="/login">
            Already have an account%s Login
        </a>
    """

    return page("Register - VIT REFOUND", body)


# ==================================================
# LOGIN
# ==================================================
@app.route("/login", methods=["GET", "POST"])
def login():

    error_message = ""

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not is_valid_vitap_email(email):

            error_message = (
                "❌ Please enter a valid VIT-AP email."
            )

        else:

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT *
                FROM users
                WHERE email = %s AND password = %s
            """, (email, password))

            user = cursor.fetchone()
            connection.close()

            if user:

                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_email"] = user["email"]

                return redirect("/dashboard")

            error_message = "❌ Invalid Email or Password!"

    body = f"""
        <h1>🔐 Login</h1>

        <form method="POST">

            <label>VIT-AP Email:</label><br>
            <input type="email"
                   name="email"
                   required>

            <br><br>

            <label>Password:</label><br>
            <input type="password"
                   name="password"
                   required>

            <br><br>

            <button type="submit">
                🔐 Login
            </button>

        </form>

        <br>

        <p class="error">
            {error_message}
        </p>

        <a href="/register">
            Don't have an account%s Register
        </a>

        <br><br>

        <a href="/forgot-password">
            🔑 Forgot Password%s
        </a>
    """

    return page("Login - VIT REFOUND", body)


# ==================================================
# FORGOT PASSWORD
# ==================================================
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    error_message = ""

    if request.method == "POST":

        email = request.form["email"].strip().lower()

        if not is_valid_vitap_email(email):

            error_message = (
                "❌ Please use a valid VIT-AP email."
            )

        else:

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (email,)
            )

            user = cursor.fetchone()
            connection.close()

            if not user:

                error_message = (
                    "❌ No account found with this VIT-AP email."
                )

            else:

                otp = str(random.randint(100000, 999999))

                session["reset_email"] = email
                session["reset_otp"] = otp
                session["reset_otp_time"] = datetime.now().timestamp()
                session["otp_attempts"] = 0

                send_otp_email(email, otp)

                return redirect("/verify-otp")

    body = f"""
        <h1>🔑 Forgot Password</h1>

        <p>
            Enter your registered VIT-AP email.
            We will send you a 6-digit OTP.
        </p>

        <form method="POST">

            <label>VIT-AP Email:</label><br>

            <input type="email"
                   name="email"
                   placeholder="Enter registered VIT-AP email"
                   required>

            <br><br>

            <button type="submit">
                📩 Send OTP
            </button>

        </form>

        <br>

        <p class="error">
            {error_message}
        </p>

        <a href="/login">
            Back to Login
        </a>
    """

    return page("Forgot Password - VIT REFOUND", body)


# ==================================================
# VERIFY OTP
# ==================================================
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():

    if (
        "reset_email" not in session
        or "reset_otp" not in session
    ):
        return redirect("/forgot-password")

    error_message = ""

    if request.method == "POST":

        entered_otp = request.form["otp"].strip()

        created_time = session.get("reset_otp_time", 0)

        age_seconds = (
            datetime.now().timestamp() - created_time
        )

        if age_seconds > OTP_EXPIRY_MINUTES * 60:

            session.pop("reset_otp", None)
            session.pop("reset_otp_time", None)
            session.pop("otp_attempts", None)

            error_message = (
                "❌ OTP expired. Please request a new OTP."
            )

        else:

            attempts = session.get("otp_attempts", 0)

            if attempts >= MAX_OTP_ATTEMPTS:

                error_message = (
                    "❌ Too many incorrect attempts. "
                    "Please request a new OTP."
                )

            elif entered_otp != session["reset_otp"]:

                session["otp_attempts"] = attempts + 1

                remaining = (
                    MAX_OTP_ATTEMPTS
                    - session["otp_attempts"]
                )

                error_message = (
                    "❌ Incorrect OTP. "
                    f"{remaining} attempt(s) remaining."
                )

            else:

                session["otp_verified"] = True

                session.pop("reset_otp", None)
                session.pop("reset_otp_time", None)
                session.pop("otp_attempts", None)

                return redirect("/reset-password")

    email = session["reset_email"]
    parts = email.split("@")

    if len(parts) == 2 and len(parts[0]) > 2:

        display_email = (
            parts[0][0]
            + "***"
            + parts[0][-1]
            + "@"
            + parts[1]
        )

    else:

        display_email = email

    body = f"""
        <h1>🔢 Verify OTP</h1>

        <p>
            Enter the 6-digit OTP sent to
            <b>{display_email}</b>.
        </p>

        <p class="small">
            OTP is valid for {OTP_EXPIRY_MINUTES} minutes.
        </p>

        <form method="POST">

            <label>6-Digit OTP:</label><br>

            <input type="text"
                   name="otp"
                   maxlength="6"
                   minlength="6"
                   inputmode="numeric"
                   required>

            <br><br>

            <button type="submit">
                ✅ Verify OTP
            </button>

        </form>

        <br>

        <p class="error">
            {error_message}
        </p>

        <a href="/forgot-password">
            Request a new OTP
        </a>
    """

    return page("Verify OTP - VIT REFOUND", body)


# ==================================================
# RESET PASSWORD
# ==================================================
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    if (
        "reset_email" not in session
        or not session.get("otp_verified")
    ):
        return redirect("/forgot-password")

    error_message = ""

    if request.method == "POST":

        new_password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if len(new_password) < 6:

            error_message = (
                "❌ Password must contain at least 6 characters."
            )

        elif new_password != confirm_password:

            error_message = "❌ Passwords do not match."

        else:

            email = session["reset_email"]

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                UPDATE users
                SET password = %s
                WHERE email = %s
            """, (new_password, email))

            connection.commit()
            connection.close()

            session.pop("reset_email", None)
            session.pop("otp_verified", None)

            return page(
                "Password Reset Successful",
                """
                <h1>✅ Password Reset Successful!</h1>

                <p class="success">
                    Your password has been changed successfully.
                </p>

                <a href="/login">
                    <button>🔐 Login Now</button>
                </a>
                """
            )

    body = f"""
        <h1>🔒 Create New Password</h1>

        <form method="POST">

            <label>New Password:</label><br>

            <input type="password"
                   name="password"
                   minlength="6"
                   required>

            <br><br>

            <label>Confirm New Password:</label><br>

            <input type="password"
                   name="confirm_password"
                   minlength="6"
                   required>

            <br><br>

            <button type="submit">
                🔒 Change Password
            </button>

        </form>

        <br>

        <p class="error">
            {error_message}
        </p>
    """

    return page("Reset Password - VIT REFOUND", body)


# ==================================================
# DASHBOARD
# ==================================================
@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    body = f"""
        <h1>🎒 VIT REFOUND</h1>

        <h2 class="center">
            Welcome, {session["user_name"]}! 👋
        </h2>

        <p class="center">
            What would you like to do%s
        </p>

        <div class="center">

            <a href="/report">
                <button>🔎 I Found an Item</button>
            </a>

            <a href="/search">
                <button>😟 I Lost an Item</button>
            </a>

            <br><br>

            <a href="/logout">
                <button>🚪 Logout</button>
            </a>

        </div>
    """

    return page("Dashboard - VIT REFOUND", body)


# ==================================================
# REPORT FOUND ITEM
# ==================================================
@app.route("/report", methods=["GET", "POST"])
def report():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        item_name = request.form["item_name"].strip()
        category = request.form["category"]
        location = request.form["location"].strip()
        date_found = request.form["date_found"]

        public_description = request.form[
            "public_description"
        ].strip()

        verification_details = request.form[
            "verification_details"
        ].strip()

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO items (
                item_name,
                category,
                location,
                date_found,
                public_description,
                verification_details,
                finder_id,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            item_name,
            category,
            location,
            date_found,
            public_description,
            verification_details,
            session["user_id"],
            "Available"
        ))

        connection.commit()
        connection.close()

        return page(
            "Item Reported",
            """
            <h1>🎉 Item Reported Successfully!</h1>

            <p class="success">
                Your found item has been added to VIT REFOUND.
            </p>

            <a href="/dashboard">
                <button>Back to Dashboard</button>
            </a>
            """
        )

    body = f"""
        <h1>🔎 Report a Found Item</h1>

        <h3>👤 Finder Details</h3>

        <p>
            <b>Name:</b>
            {session["user_name"]}
        </p>

        <p>
            <b>Email:</b>
            {session["user_email"]}
        </p>

        <hr>

        <form method="POST">

            <label>Item Name:</label><br>

            <input type="text"
                   name="item_name"
                   placeholder="Example: Wallet"
                   required>

            <br><br>

            <label>Category:</label><br>

            <select name="category">
                <option value="Electronics">
                    Electronics
                </option>
                <option value="Documents">
                    Documents
                </option>
                <option value="Accessories">
                    Accessories
                </option>
                <option value="Books">
                    Books
                </option>
                <option value="Clothing">
                    Clothing
                </option>
                <option value="Other">
                    Other
                </option>
            </select>

            <br><br>

            <label>Location Found:</label><br>

            <input type="text"
                   name="location"
                   placeholder="Example: Library"
                   required>

            <br><br>

            <label>Date Found:</label><br>

            <input type="date"
                   name="date_found"
                   required>

            <br><br>

            <label>Public Description:</label><br>

            <textarea
                name="public_description"
                placeholder="General description visible in search."
            ></textarea>

            <br><br>

            <h3>🔒 Secret Verification Details</h3>

            <p>
                Enter details that only the real owner can identify.
            </p>

            <textarea
                name="verification_details"
                placeholder="Example: Black colour, red sticker inside, small scratch on the back, initials AS..."
                required
            ></textarea>

            <br><br>

            <button type="submit">
                📤 Report Item
            </button>

        </form>

        <br>

        <a href="/dashboard">
            Back to Dashboard
        </a>
    """

    return page("Report Found Item - VIT REFOUND", body)


# ==================================================
# SMART SEARCH
# ==================================================
@app.route("/search", methods=["GET", "POST"])
def search():

    if "user_id" not in session:
        return redirect("/login")

    results = []

    if request.method == "POST":

        search_item = request.form["search_item"].strip()

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                item_name,
                category,
                location,
                date_found,
                public_description,
                status
            FROM items
        """)

        all_items = cursor.fetchall()
        connection.close()

        for item in all_items:

            score = smart_item_score(
                search_item,
                item["item_name"],
                item["category"],
                item["location"],
                item["public_description"] or ""
            )

            if score >= 28:
                results.append((score, item))

        results.sort(
            key=lambda x: x[0],
            reverse=True
        )

    results_html = ""

    if results:

        results_html = "<h2>📦 Smart Search Results</h2>"

        for score, item in results:

            if score >= 75:
                label = "Very Strong Match"
            elif score >= 55:
                label = "Strong Match"
            else:
                label = "Possible Match"

            results_html += f"""
            <div class="result">

                <h3>
                    📦 {item["item_name"]}
                </h3>

                <span class="match">
                    🧠 {label} — {score}%
                </span>

                <p>
                    <b>Category:</b>
                    {item["category"]}
                </p>

                <p>
                    <b>Location Found:</b>
                    {item["location"]}
                </p>

                <p>
                    <b>Date Found:</b>
                    {item["date_found"]}
                </p>

                <p>
                    <b>Description:</b>
                    {item["public_description"]
                     or "No public description"}
                </p>
            """

            if item["status"] == "Available":

                results_html += f"""
                    <p>
                        <b>Status:</b> 🟢 Available
                    </p>

                    <a href="/claim/{item["id"]}">
                        <button>
                            🔐 Verify & Claim Item
                        </button>
                    </a>
                """

            elif item["status"] == "Claimed":

                results_html += """
                    <p>
                        <b>Status:</b> 🟠 Claimed
                    </p>

                    <p>
                        This item is currently under
                        a verified claim.
                    </p>
                """

            else:

                results_html += """
                    <p class="returned">
                        <b>Status:</b> 🔴 Returned
                    </p>

                    <h3>
                        ⚠️ This item has already been returned
                        to its owner.
                    </h3>
                """

            results_html += "</div>"

    elif request.method == "POST":

        results_html = """
            <h3>❌ No matching items found.</h3>

            <p>
                Try another spelling, related word,
                category, or location.
            </p>
        """

    body = f"""
        <h1>😟 Smart Search for Your Lost Item</h1>

        <p>
            VIT REFOUND understands related words,
            spelling variations, partial words,
            categories, locations and descriptions.
        </p>

        <form method="POST">

            <label>
                Enter Item Name or Keywords:
            </label><br>

            <input type="text"
                   name="search_item"
                   placeholder="Example: key chain, mobile, black wallet"
                   required>

            <br><br>

            <button type="submit">
                🧠 Smart Search
            </button>

        </form>

        <br>

        {results_html}

        <br>

        <a href="/dashboard">
            <button>Back to Dashboard</button>
        </a>
    """

    return page("Smart Search - VIT REFOUND", body)


# ==================================================
# VERIFY & CLAIM
# ==================================================
@app.route("/claim/<int:item_id>", methods=["GET", "POST"])
def claim_item(item_id):

    if "user_id" not in session:
        return redirect("/login")

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            items.*,
            users.name AS finder_name,
            users.email AS finder_email
        FROM items
        JOIN users
        ON items.finder_id = users.id
        WHERE items.id = %s
    """, (item_id,))

    item = cursor.fetchone()
    connection.close()

    if not item:

        return page(
            "Item Not Found",
            """
            <h2>❌ Item Not Found!</h2>
            <a href="/search">Back to Search</a>
            """
        )

    if item["status"] == "Returned":

        return page(
            "Item Returned",
            """
            <h2>
                🔴 This item has already been returned.
            </h2>

            <a href="/search">
                Back to Search
            </a>
            """
        )

    # Prevent another user from claiming an item already claimed.
    if item["status"] == "Claimed":

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM claims
            WHERE item_id = %s
            AND claimant_id = %s
            AND verified = 1
        """, (item_id, session["user_id"]))

        own_claim = cursor.fetchone()
        connection.close()

        if not own_claim:

            return page(
                "Item Claimed",
                """
                <h2>
                    🟠 This item is already claimed.
                </h2>

                <p>
                    Another verified claimant is currently
                    handling this item.
                </p>

                <a href="/search">
                    Back to Search
                </a>
                """
            )

    if request.method == "POST":

        user_verification = request.form[
            "verification"
        ].strip()

        matched, common_words, score = verification_matches(
            item["verification_details"],
            user_verification
        )

        if matched:

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT *
                FROM claims
                WHERE item_id = %s
                AND claimant_id = %s
            """, (
                item_id,
                session["user_id"]
            ))

            existing_claim = cursor.fetchone()

            if not existing_claim:

                cursor.execute("""
                    INSERT INTO claims (
                        item_id,
                        claimant_id,
                        verified,
                        received
                    )
                    VALUES (%s, %s, %s, %s)
                """, (
                    item_id,
                    session["user_id"],
                    1,
                    0
                ))

            else:

                cursor.execute("""
                    UPDATE claims
                    SET verified = 1
                    WHERE item_id = %s
                    AND claimant_id = %s
                """, (
                    item_id,
                    session["user_id"]
                ))

            # Item becomes claimed after successful verification.
            cursor.execute("""
                UPDATE items
                SET status = 'Claimed'
                WHERE id = %s
            """, (item_id,))

            connection.commit()
            connection.close()

            matched_display = ", ".join(
                sorted(common_words)
            )

            return page(
                "Verification Successful",
                f"""
                <h1>
                    🎉 Verification Successful!
                </h1>

                <h2>
                    ✅ You successfully claimed this item.
                </h2>

                <p class="success">
                    Smart verification score:
                    <b>{score}%</b>
                </p>

                <p>
                    Matching details detected:
                    <b>{matched_display}</b>
                </p>

                <hr>

                <h3>👤 Finder Details</h3>

                <p>
                    <b>Name:</b>
                    {item["finder_name"]}
                </p>

                <p>
                    <b>Email:</b>
                    {item["finder_email"]}
                </p>

                <hr>

                <h3>📦 Next Step</h3>

                <p>
                    Contact the finder using the details above
                    to arrange collection of your item.
                </p>

                <h3>
                    Have you received your item%s
                </h3>

                <form method="POST"
                      action="/received/{item_id}">

                    <button type="submit"
                            name="answer"
                            value="yes">
                        ✅ Yes, I Received It
                    </button>

                    <br><br>

                    <button type="submit"
                            name="answer"
                            value="no">
                        ❌ No, Not Yet
                    </button>

                </form>

                <br>

                <a href="/dashboard">
                    <button>
                        Back to Dashboard
                    </button>
                </a>
                """
            )

        return page(
            "Verification Failed",
            f"""
            <h1>❌ Verification Failed</h1>

            <h3>
                Your details matched
                <b>{score}%</b>
                of the important verification information.
            </h3>

            <p>
                At least <b>50%</b> meaningful verification
                information is required to claim this item.
            </p>

            <p>
                Try again with more details that only
                the real owner would know.
            </p>

            <a href="/claim/{item_id}">
                <button>🔄 Try Again</button>
            </a>

            <br><br>

            <a href="/search">
                Back to Search
            </a>
            """
        )

    body = f"""
        <h1>🔐 Verify & Claim Item</h1>

        <div class="info">

            <h2>
                📦 {item["item_name"]}
            </h2>

            <p>
                <b>Category:</b>
                {item["category"]}
            </p>

            <p>
                <b>Location Found:</b>
                {item["location"]}
            </p>

            <p>
                <b>Date Found:</b>
                {item["date_found"]}
            </p>

        </div>

        <hr>

        <h3>
            🔒 Tell us something only the owner would know
        </h3>

        <p>
            Enter private details about your item.
            Exact wording is not required.
            A 50% or higher meaningful match can proceed.
        </p>

        <ul>
            <li>🎨 Colour</li>
            <li>🔑 Items inside</li>
            <li>✏️ Unique marks</li>
            <li>🔖 Stickers</li>
            <li>🩹 Scratches</li>
            <li>🔤 Initials or name</li>
            <li>⭐ Any other unique detail</li>
        </ul>

        <form method="POST">

            <textarea
                name="verification"
                rows="7"
                placeholder="Example: My wallet is black, has a red sticker inside, a scratch near the zip, and my initials AS..."
                required
            ></textarea>

            <br><br>

            <button type="submit">
                🔐 Verify & Claim
            </button>

        </form>

        <br>

        <a href="/search">
            Back to Search
        </a>
    """

    return page("Verify Item - VIT REFOUND", body)


# ==================================================
# RECEIVED / RETURNED
# ==================================================
@app.route("/received/<int:item_id>", methods=["POST"])
def received_item(item_id):

    if "user_id" not in session:
        return redirect("/login")

    answer = request.form.get(
        "answer",
        ""
    ).strip().lower()

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM claims
        WHERE item_id = %s
        AND claimant_id = %s
        AND verified = 1
    """, (
        item_id,
        session["user_id"]
    ))

    claim = cursor.fetchone()

    if not claim:

        connection.close()

        return page(
            "Not Authorized",
            """
            <h2>
                ❌ You are not authorized for this claim.
            </h2>

            <a href="/dashboard">
                Back to Dashboard
            </a>
            """
        )

    # Check NO first.
    no_answers = {
        "no",
        "not yet",
        "not received",
        "haven't received",
        "have not received",
        "i haven't received it",
        "i have not received it",
        "no i haven't",
        "no i have not"
    }

    yes_answers = {
        "yes",
        "received",
        "yes received",
        "i received it",
        "i have received it",
        "got it",
        "got my item",
        "received my item",
        "yes i received it",
        "yes i have received it"
    }

    normalized_answer = re.sub(
        r"[^a-z0-9\s']",
        "",
        answer
    )

    normalized_answer = re.sub(
        r"\s+",
        " ",
        normalized_answer
    ).strip()

    if (
        normalized_answer in no_answers
        or normalized_answer.startswith("no ")
        or "not received" in normalized_answer
        or "haven't received" in normalized_answer
        or "have not received" in normalized_answer
    ):

        connection.close()

        return page(
            "Item Not Yet Received",
            """
            <h1>📦 Item Still Claimed</h1>

            <p>
                The item will remain claimed until
                you confirm that you received it.
            </p>

            <a href="/dashboard">
                <button>Back to Dashboard</button>
            </a>
            """
        )

    if (
        normalized_answer in yes_answers
        or normalized_answer.startswith("yes ")
        or "received my item" in normalized_answer
        or "i received it" in normalized_answer
        or "i have received it" in normalized_answer
        or normalized_answer == "got it"
    ):

        cursor.execute("""
            UPDATE claims
            SET received = 1
            WHERE item_id = %s
            AND claimant_id = %s
        """, (
            item_id,
            session["user_id"]
        ))

        cursor.execute("""
            UPDATE items
            SET status = 'Returned'
            WHERE id = %s
        """, (item_id,))

        connection.commit()
        connection.close()

        return page(
            "Item Returned",
            """
            <h1>
                ✅ Item Returned Successfully!
            </h1>

            <p class="success">
                The item has been marked as Returned.
            </p>

            <p>
                Thank you for confirming the return.
            </p>

            <a href="/search">
                <button>Back to Search</button>
            </a>
            """
        )

    connection.close()

    return page(
        "Invalid Answer",
        """
        <h2>⚠️ Please answer clearly.</h2>

        <p>
            Use <b>Yes</b> if you received your item,
            or <b>No</b> if you have not received it yet.
        </p>

        <a href="/dashboard">
            <button>Back to Dashboard</button>
        </a>
        """
    )


# ==================================================
# LOGOUT
# ==================================================
@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ==================================================
# RUN
# =================================================
if __name__ == "__main__":
    app.run(debug=True)
