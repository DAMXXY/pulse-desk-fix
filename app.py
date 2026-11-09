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
from sqlalchemy import UniqueConstraint, or_
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent


def _database_uri(database_url):
    if not database_url:
        return f"sqlite:///{BASE_DIR / 'support.db'}"
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


app = Flask(__name__)


def _stylesheet_version(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except FileNotFoundError:
        app.logger.warning("Static stylesheet is missing: %s", path)
        return None


app.jinja_env.globals["style_version"] = _stylesheet_version(
    BASE_DIR / "static" / "style.css"
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "academic-prototype-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri(
    os.environ.get("DATABASE_URL")
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


class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_name = db.Column(db.String(120), nullable=False)
    sender_email = db.Column(db.String(160), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    system = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    status = db.Column(db.String(40), nullable=False, default="Needs Review")
    info_request = db.Column(db.Text)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"))
    received_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class TicketActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    actor = db.relationship("User")
    action = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class TicketApproval(db.Model):
    __table_args__ = (UniqueConstraint("ticket_id", "role", name="uq_ticket_approval_role"),)

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("ticket.id"), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    approver = db.relationship("User")
    role = db.Column(db.String(40), nullable=False)
    note = db.Column(db.Text, nullable=False, default="")
    approved_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


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


@app.route("/accounts", methods=["GET", "POST"])
@roles_required("Administrator")
def accounts():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        allowed_roles = {"IT Support Officer", "IT Supervisor"}

        if not name or not email or len(password) < 8 or role not in allowed_roles:
            flash("Enter a name, email, valid staff role, and password of at least 8 characters.", "danger")
            return redirect(url_for("accounts"))
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("accounts"))

        db.session.add(
            User(
                name=name,
                email=email,
                password=generate_password_hash(password),
                role=role,
            )
        )
        db.session.commit()
        flash(f"Created the {role} account for {name}.", "success")
        return redirect(url_for("accounts"))

    return render_template(
        "accounts.html",
        users=User.query.order_by(User.role, User.name).all(),
    )


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
        "ticket_queue.html", tickets=query.order_by(Ticket.created_at.desc()).all()
    )


@app.route("/tickets/new", methods=["GET", "POST"])
@roles_required("IT Support Officer")
def new_ticket():
    return redirect(url_for("complaints"))


@app.route("/complaints", methods=["GET", "POST"])
@roles_required("IT Support Officer")
def complaints():
    if request.method == "POST":
        branch_id = request.form.get("branch_id", type=int)
        branch = db.session.get(Branch, branch_id) if branch_id else None
        fields = {
            "sender_name": request.form.get("sender_name", "").strip(),
            "sender_email": request.form.get("sender_email", "").strip(),
            "subject": request.form.get("subject", "").strip(),
            "message": request.form.get("message", "").strip(),
            "system": request.form.get("system", "").strip(),
            "category": request.form.get("category", "").strip(),
            "priority": request.form.get("priority", "Medium"),
        }
        if not branch or any(not value for value in fields.values()):
            flash("Complete the sender, branch, issue, and complaint details.", "danger")
            return redirect(url_for("complaints"))

        if fields["priority"] not in {"Low", "Medium", "High"}:
            flash("Choose a valid priority.", "danger")
            return redirect(url_for("complaints"))

        complaint = Complaint(
            **fields,
            branch_id=branch.id,
            received_by_id=current_user().id,
        )
        db.session.add(complaint)
        db.session.commit()
        flash("Incoming complaint added to the intake inbox.", "success")
        return redirect(url_for("complaints"))

    return render_template(
        "complaints.html",
        complaints=Complaint.query.order_by(Complaint.created_at.desc()).all(),
        branches=Branch.query.order_by(Branch.branch_name).all(),
    )


@app.post("/complaints/<int:complaint_id>/request-info")
@roles_required("IT Support Officer")
def request_complaint_info(complaint_id):
    complaint = db.get_or_404(Complaint, complaint_id)
    if complaint.ticket_id:
        flash("This complaint has already been forwarded to the supervisor.", "warning")
        return redirect(url_for("complaints"))

    message = request.form.get("info_request", "").strip()
    if not message:
        flash("Write the information you need from the sender.", "danger")
        return redirect(url_for("complaints"))

    complaint.info_request = message
    complaint.status = "Awaiting Sender"
    db.session.commit()
    flash("Information request saved as a draft. Send it through your normal email.", "success")
    return redirect(url_for("complaints"))


@app.post("/complaints/<int:complaint_id>/sender-reply")
@roles_required("IT Support Officer")
def record_sender_reply(complaint_id):
    complaint = db.get_or_404(Complaint, complaint_id)
    if complaint.ticket_id or complaint.status != "Awaiting Sender":
        flash("This complaint is not waiting for a sender response.", "warning")
        return redirect(url_for("complaints"))

    reply = request.form.get("sender_reply", "").strip()
    if not reply:
        flash("Enter the sender's additional information.", "danger")
        return redirect(url_for("complaints"))

    complaint.message = f"{complaint.message}\n\nSender follow-up:\n{reply}"
    complaint.status = "Needs Review"
    db.session.commit()
    flash("Sender response recorded. The complaint is ready for review.", "success")
    return redirect(url_for("complaints"))


@app.post("/complaints/<int:complaint_id>/forward")
@roles_required("IT Support Officer")
def forward_complaint(complaint_id):
    complaint = db.get_or_404(Complaint, complaint_id)
    if complaint.ticket_id:
        flash("This complaint has already been forwarded.", "warning")
        return redirect(url_for("ticket_detail", ticket_id=complaint.ticket_id))
    if complaint.status == "Awaiting Sender":
        flash("Record the sender's reply before forwarding this complaint.", "warning")
        return redirect(url_for("complaints"))

    ticket = Ticket(
        ticket_number="PENDING",
        branch_id=complaint.branch_id,
        reported_by=complaint.sender_name,
        category=complaint.category,
        system=complaint.system,
        description=f"{complaint.subject}\n\n{complaint.message}",
        priority=complaint.priority,
        status="Open",
    )
    db.session.add(ticket)
    db.session.flush()
    ticket.ticket_number = f"TKT-{ticket.id:05d}"
    complaint.status = "Forwarded to Supervisor"
    complaint.ticket_id = ticket.id
    db.session.add(
        TicketActivity(
            ticket_id=ticket.id,
            actor_id=current_user().id,
            action="Complaint received",
            message=f"Received from {complaint.sender_name} ({complaint.sender_email}) and forwarded for assignment.",
        )
    )
    detect_patterns()
    db.session.commit()
    flash(f"Complaint forwarded as {ticket.ticket_number} for supervisor assignment.", "success")
    return redirect(url_for("ticket_detail", ticket_id=ticket.id))


@app.route("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    user = current_user()
    template = "ticket_detail_workflow.html"
    approvals = {
        approval.role: approval
        for approval in TicketApproval.query.filter_by(ticket_id=ticket.id).all()
    }
    return render_template(
        template,
        ticket=ticket,
        activities=TicketActivity.query.filter_by(ticket_id=ticket.id)
        .order_by(TicketActivity.created_at.asc())
        .all(),
        approvals=approvals,
        agents=User.query.filter_by(role="IT Support Officer").order_by(User.name).all(),
        can_update=ticket.assigned_to == user.name,
    )


@app.post("/tickets/<int:ticket_id>/assign")
@roles_required("IT Supervisor")
def assign_ticket(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    agent = User.query.filter_by(
        name=request.form.get("assigned_to", "").strip(),
        role="IT Support Officer",
    ).first()
    if not agent or ticket.status in {"Pending Approval", "Resolved"}:
        flash("Choose an officer and a ticket that is awaiting assignment.", "danger")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    ticket.assigned_to = agent.name
    ticket.status = "Assigned"
    db.session.add(
        TicketActivity(
            ticket_id=ticket.id,
            actor_id=current_user().id,
            action="Assigned",
            message=f"Assigned to {agent.name}.",
        )
    )
    db.session.commit()
    flash(f"{ticket.ticket_number} assigned to {agent.name}.", "success")
    return redirect(url_for("ticket_detail", ticket_id=ticket.id))


@app.post("/tickets/<int:ticket_id>/progress")
@roles_required("IT Support Officer")
def update_ticket_progress(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    user = current_user()
    if ticket.assigned_to != user.name:
        flash("Only the assigned officer can update this ticket.", "danger")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))
    if ticket.status not in {"Assigned", "In Progress", "Waiting on Branch"}:
        flash("This ticket is not accepting progress updates.", "warning")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    action = request.form.get("action")
    message = request.form.get("message", "").strip()
    if not message:
        flash("Add a note describing the work completed.", "danger")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    if action == "submit-resolution":
        ticket.status = "Pending Approval"
        activity_action = "Resolution submitted"
    elif action == "log-progress":
        status = request.form.get("status")
        if status not in {"In Progress", "Waiting on Branch"}:
            flash("Choose a valid work status.", "danger")
            return redirect(url_for("ticket_detail", ticket_id=ticket.id))
        ticket.status = status
        activity_action = status
    else:
        flash("Choose a valid work action.", "danger")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    db.session.add(
        TicketActivity(
            ticket_id=ticket.id,
            actor_id=user.id,
            action=activity_action,
            message=message,
        )
    )
    db.session.commit()
    flash("Resolution submitted for approval." if action == "submit-resolution" else "Progress recorded.", "success")
    return redirect(url_for("ticket_detail", ticket_id=ticket.id))


@app.post("/tickets/<int:ticket_id>/approve")
@roles_required("IT Supervisor", "Administrator")
def approve_ticket_resolution(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    user = current_user()
    if ticket.status != "Pending Approval":
        flash("Only submitted resolutions can be approved.", "warning")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    if TicketApproval.query.filter_by(ticket_id=ticket.id, role=user.role).first():
        flash("Your role has already approved this resolution.", "warning")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    note = request.form.get("note", "").strip()
    if not note:
        flash("Add a review note before approving the resolution.", "danger")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    db.session.add(
        TicketApproval(
            ticket_id=ticket.id,
            approver_id=user.id,
            role=user.role,
            note=note,
        )
    )
    db.session.add(
        TicketActivity(
            ticket_id=ticket.id,
            actor_id=user.id,
            action=f"{user.role} approval",
            message=note,
        )
    )
    approval_roles = {
        approval.role
        for approval in TicketApproval.query.filter_by(ticket_id=ticket.id).all()
    }
    approval_roles.add(user.role)
    if {"IT Supervisor", "Administrator"}.issubset(approval_roles):
        ticket.status = "Resolved"
        ticket.resolved_at = datetime.utcnow()
        db.session.add(
            TicketActivity(
                ticket_id=ticket.id,
                actor_id=user.id,
                action="Closed",
                message="Supervisor and administrator approvals are complete.",
            )
        )
    db.session.commit()
    flash(
        "Both approvals are complete. The ticket is closed."
        if ticket.status == "Resolved"
        else f"{user.role} approval recorded. Awaiting the other approval.",
        "success",
    )
    return redirect(url_for("ticket_detail", ticket_id=ticket.id))


@app.route("/updates", methods=["GET", "POST"])
@roles_required("IT Supervisor")
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
@roles_required("IT Supervisor")
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
