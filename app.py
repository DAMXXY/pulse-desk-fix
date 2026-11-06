import hashlib
import os
import random
from collections import Counter
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    make_response,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.jinja_env.globals["style_version"] = hashlib.sha256(
    (BASE_DIR / "static" / "style.css").read_bytes()
).hexdigest()[:12]
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "academic-prototype-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = (
    os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'support.db'}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="IT Support Officer")


class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    branch_name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(120), nullable=False)
    tickets = db.relationship("Ticket", backref="branch", lazy=True)


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(30), unique=True, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    reported_by = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    system = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    status = db.Column(db.String(30), nullable=False, default="Open")
    assigned_to = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)


class Update(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    system = db.Column(db.String(100), nullable=False)
    version = db.Column(db.String(50), nullable=False)
    deployment_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)


class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), nullable=False, default="Medium")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String(30), nullable=False, default="Active")
    related_ticket_ids = db.Column(db.Text, default="")


def current_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login", next=request.path))
            if user.role not in roles:
                flash("Your role does not have permission for that action.", "danger")
                return redirect(request.referrer or url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def ticket_ids(tickets):
    return ",".join(str(ticket.id) for ticket in tickets)


def detect_patterns():
    open_tickets = Ticket.query.filter(Ticket.status != "Resolved").all()
    grouped = {}
    for ticket in open_tickets:
        key = (ticket.system.lower(), ticket.category.lower())
        grouped.setdefault(key, []).append(ticket)
    for (system, category), matches in grouped.items():
        if len(matches) < 5:
            continue
        title = f"Recurring incident detected: {matches[0].system}"
        if not Alert.query.filter_by(title=title, status="Active").first():
            db.session.add(
                Alert(
                    title=title,
                    description=f"{len(matches)} similar {category} incidents detected for {matches[0].system}. Review the related tickets for a shared cause.",
                    severity="High",
                    related_ticket_ids=ticket_ids(matches),
                )
            )
    for update in Update.query.all():
        matches = Ticket.query.filter(
            Ticket.system.ilike(f"%{update.system}%"),
            Ticket.created_at
            >= datetime.combine(update.deployment_date, datetime.min.time()),
        ).all()
        title = f"Potential update correlation: {update.system} {update.version}"
        if (
            len(matches) >= 5
            and not Alert.query.filter_by(title=title, status="Active").first()
        ):
            db.session.add(
                Alert(
                    title=title,
                    description=f"{len(matches)} incidents were logged after {update.system} version {update.version} was deployed.",
                    severity="Medium",
                    related_ticket_ids=ticket_ids(matches),
                )
            )


def seed_data():
    if User.query.first():
        return
    db.session.add_all(
        [
            User(
                name="Amina Yusuf",
                email="officer@pulsedesk.test",
                password=generate_password_hash("demo123"),
                role="IT Support Officer",
            ),
            User(
                name="Daniel Okafor",
                email="supervisor@pulsedesk.test",
                password=generate_password_hash("demo123"),
                role="IT Supervisor",
            ),
            User(
                name="Grace Mensah",
                email="admin@pulsedesk.test",
                password=generate_password_hash("demo123"),
                role="Administrator",
            ),
        ]
    )
    db.session.add_all(
        [
            Branch(branch_name=name, location=location)
            for name, location in [
                ("Lagos Central", "Lagos"),
                ("Abuja North", "Abuja"),
                ("Ibadan Main", "Ibadan"),
                ("Port Harcourt", "Port Harcourt"),
                ("Ikeja", "Lagos"),
                ("Yaba", "Lagos"),
                ("Surulere", "Lagos"),
            ]
        ]
    )
    db.session.commit()


@app.route("/demo-data", methods=["GET", "POST"])
@roles_required("Administrator")
def demo_data():
    if request.method == "POST":
        try:
            ticket_count = max(10, min(int(request.form["ticket_count"]), 250))
            update_count = max(1, min(int(request.form["update_count"]), 10))
            start_date = datetime.strptime(request.form["start_date"], "%Y-%m-%d")
            end_date = datetime.strptime(request.form["end_date"], "%Y-%m-%d")
            if end_date < start_date:
                raise ValueError("The end date must be after the start date.")
        except (KeyError, TypeError, ValueError):
            flash("Enter a valid date range and numeric activity volumes.", "danger")
            return redirect(url_for("demo_data"))

        branch_pool = Branch.query.all()
        staff_pool = User.query.all()
        systems = [
            value.strip()
            for value in request.form["systems"].split(",")
            if value.strip()
        ]
        categories = [
            value.strip()
            for value in request.form["categories"].split(",")
            if value.strip()
        ]
        if not branch_pool or not staff_pool or not systems or not categories:
            flash(
                "Add at least one system and category before generating activity.",
                "danger",
            )
            return redirect(url_for("demo_data"))

        generator = random.Random()
        day_span = max((end_date - start_date).days, 1)
        descriptions = {
            "Application": [
                "is slow and freezing during normal use",
                "shows an error after sign in",
                "takes too long to load",
                "failed during a routine transaction",
            ],
            "Network": [
                "cannot connect to the branch network",
                "drops connection intermittently",
                "has slow access from several workstations",
            ],
            "Hardware": [
                "is not powering on",
                "is producing an error light",
                "needs inspection after repeated failure",
            ],
            "Access": [
                "rejects valid credentials",
                "does not show the expected permissions",
                "is locking users out unexpectedly",
            ],
            "Other": [
                "needs investigation by the support team",
                "is affecting normal branch operations",
                "was reported by multiple staff members",
            ],
        }
        created = []
        for index in range(ticket_count):
            system = systems[0] if index < 5 else generator.choice(systems)
            category = categories[0] if index < 5 else generator.choice(categories)
            created_at = start_date + timedelta(
                days=generator.randint(0, day_span),
                hours=generator.randint(8, 17),
                minutes=generator.randint(0, 59),
            )
            age = (end_date - created_at).days
            status = generator.choices(
                ["Resolved", "In Progress", "Assigned", "Open"],
                weights=[45, 20, 15, 20] if age > 14 else [20, 25, 20, 35],
            )[0]
            priority = generator.choices(
                ["High", "Medium", "Low"], weights=[18, 57, 25]
            )[0]
            ticket = Ticket(
                ticket_number="PENDING",
                branch_id=generator.choice(branch_pool).id,
                reported_by=generator.choice(staff_pool).name,
                category=category,
                system=system,
                description=f"{system} {generator.choice(descriptions.get(category, descriptions['Other']))}.",
                priority=priority,
                status=status,
                assigned_to=(
                    generator.choice(staff_pool).name if status != "Open" else None
                ),
                created_at=created_at,
                resolved_at=(
                    created_at + timedelta(days=generator.randint(1, 5))
                    if status == "Resolved"
                    else None
                ),
            )
            db.session.add(ticket)
            db.session.flush()
            ticket.ticket_number = f"TKT-{ticket.id:05d}"
            created.append(ticket)

        for index in range(update_count):
            system = systems[index % len(systems)]
            deployment_date = (
                start_date + timedelta(days=generator.randint(0, day_span))
            ).date()
            db.session.add(
                Update(
                    system=system,
                    version=f"{generator.randint(3, 5)}.{generator.randint(0, 9)}",
                    deployment_date=deployment_date,
                    description=f"Routine {system} deployment recorded for the demo activity period.",
                )
            )
        detect_patterns()
        db.session.commit()
        flash(
            f"Generated {len(created)} tickets and {update_count} system updates across the selected period.",
            "success",
        )
        return redirect(url_for("dashboard"))

    today = datetime.utcnow().date()
    return render_template(
        "demo_data.html",
        end_date=today.isoformat(),
        start_date=(today - timedelta(days=60)).isoformat(),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(email=request.form["email"].strip().lower()).first()
        if user and check_password_hash(user.password, request.form["password"]):
            session["user_id"] = user.id
            flash(f"Welcome back, {user.name.split()[0]}.", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Those demo credentials did not match.", "danger")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    stats = {
        "total": Ticket.query.count(),
        "open": Ticket.query.filter(Ticket.status != "Resolved").count(),
        "resolved": Ticket.query.filter_by(status="Resolved").count(),
        "high": Ticket.query.filter_by(priority="High")
        .filter(Ticket.status != "Resolved")
        .count(),
    }
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_tickets=Ticket.query.order_by(Ticket.created_at.desc()).limit(6).all(),
        active_alerts=Alert.query.filter_by(status="Active")
        .order_by(Alert.created_at.desc())
        .limit(4)
        .all(),
        category_counts=Counter(
            ticket.category for ticket in Ticket.query.all()
        ).most_common(5),
    )


@app.route("/tickets")
@login_required
def tickets():
    search, status, priority = (
        request.args.get("search", "").strip(),
        request.args.get("status", ""),
        request.args.get("priority", ""),
    )
    query = Ticket.query
    if search:
        term = f"%{search}%"
        query = query.join(Branch).filter(
            or_(
                Ticket.ticket_number.ilike(term),
                Ticket.category.ilike(term),
                Ticket.system.ilike(term),
                Ticket.description.ilike(term),
                Branch.branch_name.ilike(term),
            )
        )
    if status:
        query = query.filter_by(status=status)
    if priority:
        query = query.filter_by(priority=priority)
    return render_template(
        "tickets.html", tickets=query.order_by(Ticket.created_at.desc()).all()
    )


@app.route("/tickets/new", methods=["GET", "POST"])
@roles_required("IT Support Officer")
def new_ticket():
    branches, agents = (
        Branch.query.order_by(Branch.branch_name).all(),
        User.query.order_by(User.name).all(),
    )
    if request.method == "POST":
        ticket = Ticket(
            ticket_number="PENDING",
            branch_id=request.form["branch_id"],
            reported_by=request.form["reported_by"].strip(),
            category=request.form["category"].strip(),
            system=request.form["system"].strip(),
            description=request.form["description"].strip(),
            priority=request.form["priority"],
            assigned_to=request.form.get("assigned_to") or None,
        )
        db.session.add(ticket)
        db.session.flush()
        ticket.ticket_number = f"TKT-{ticket.id:05d}"
        detect_patterns()
        db.session.commit()
        flash(f"Ticket {ticket.ticket_number} was logged successfully.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))
    return render_template("new_ticket.html", branches=branches, agents=agents)


@app.route("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    return render_template(
        "ticket_detail.html", ticket=db.get_or_404(Ticket, ticket_id)
    )


@app.post("/tickets/<int:ticket_id>/update")
@roles_required("IT Supervisor", "Administrator")
def update_ticket(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    ticket.status, ticket.priority, ticket.assigned_to = (
        request.form["status"],
        request.form["priority"],
        request.form.get("assigned_to") or None,
    )
    ticket.resolved_at = datetime.utcnow() if ticket.status == "Resolved" else None
    detect_patterns()
    db.session.commit()
    flash(f"{ticket.ticket_number} was updated.", "success")
    return redirect(request.referrer or url_for("tickets"))


@app.route("/updates", methods=["GET", "POST"])
@roles_required("IT Supervisor", "Administrator")
def updates():
    if request.method == "POST":
        db.session.add(
            Update(
                system=request.form["system"].strip(),
                version=request.form["version"].strip(),
                deployment_date=datetime.strptime(
                    request.form["deployment_date"], "%Y-%m-%d"
                ).date(),
                description=request.form["description"].strip(),
            )
        )
        detect_patterns()
        db.session.commit()
        flash("System update recorded.", "success")
        return redirect(url_for("updates"))
    return render_template(
        "updates.html",
        updates=Update.query.order_by(Update.deployment_date.desc()).all(),
    )


@app.route("/alerts")
@login_required
def alerts():
    return render_template(
        "alerts.html", alerts=Alert.query.order_by(Alert.created_at.desc()).all()
    )


@app.route("/alerts/<int:alert_id>")
@login_required
def alert_detail(alert_id):
    alert = db.get_or_404(Alert, alert_id)
    ids = [int(value) for value in alert.related_ticket_ids.split(",") if value]
    related_tickets = (
        Ticket.query.filter(Ticket.id.in_(ids)).order_by(Ticket.created_at.desc()).all()
        if ids
        else []
    )
    return render_template(
        "alert_detail.html", alert=alert, related_tickets=related_tickets
    )


@app.post("/alerts/<int:alert_id>/close")
@roles_required("IT Supervisor", "Administrator")
def close_alert(alert_id):
    alert = db.get_or_404(Alert, alert_id)
    alert.status = "Closed"
    db.session.commit()
    flash("Alert marked as reviewed.", "success")
    return redirect(request.referrer or url_for("alerts"))


@app.route("/reports")
@login_required
def reports():
    tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    stats = {
        "total": len(tickets),
        "open": sum(ticket.status != "Resolved" for ticket in tickets),
        "resolved": sum(ticket.status == "Resolved" for ticket in tickets),
        "high": sum(
            ticket.priority == "High" and ticket.status != "Resolved"
            for ticket in tickets
        ),
    }
    return render_template(
        "reports.html",
        stats=stats,
        category_counts=Counter(ticket.category for ticket in tickets).most_common(),
        tickets=tickets,
    )


@app.get("/reports.csv")
@login_required
def report_csv():
    rows = ["Ticket,Branch,System,Category,Priority,Status,Created"]
    rows.extend(
        ",".join(
            [
                ticket.ticket_number,
                ticket.branch.branch_name,
                ticket.system,
                ticket.category,
                ticket.priority,
                ticket.status,
                ticket.created_at.strftime("%Y-%m-%d"),
            ]
        )
        for ticket in Ticket.query.order_by(Ticket.created_at.desc()).all()
    )
    response = make_response("\n".join(rows))
    response.headers["Content-Disposition"] = "attachment; filename=ticket-report.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


with app.app_context():
    db.create_all()
    seed_data()

app.add_url_rule(
    "/demo-data", endpoint="demo_data", view_func=demo_data, methods=["GET", "POST"]
)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
