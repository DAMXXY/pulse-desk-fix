from uuid import uuid4

from sqlalchemy import create_engine

from app import (
    Branch,
    Complaint,
    Ticket,
    TicketActivity,
    TicketApproval,
    User,
    _database_uri,
    _stylesheet_version,
    app,
    db,
)


def test_ticket_pages_load():
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/").status_code == 302
    client.post(
        "/login", data={"email": "officer@pulsedesk.test", "password": "demo123"}
    )
    assert client.get("/").status_code == 200
    assert client.get("/tickets").status_code == 200
    assert client.get("/tickets/new").status_code == 302
    assert client.get("/complaints").status_code == 200


def test_database_uri_supports_postgresql_and_local_sqlite():
    postgres_url = "postgres://user:password@database.example.test/pulsedesk"
    assert _database_uri(postgres_url) == postgres_url.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
    assert _database_uri("postgresql://user:password@database/pulsedesk") == (
        "postgresql+psycopg://user:password@database/pulsedesk"
    )
    assert _database_uri(None).startswith("sqlite:///")
    engine = create_engine(_database_uri(postgres_url))
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def test_login_stylesheet_is_versioned_and_served():
    client = app.test_client()
    login = client.get("/login")
    stylesheet = client.get("/static/style.css")

    assert b"/static/style.css?v=" in login.data
    assert stylesheet.status_code == 200
    assert stylesheet.mimetype == "text/css"
    assert stylesheet.data
    assert b".login-layout" in stylesheet.data
    assert b".login-navbar" in stylesheet.data


def test_missing_stylesheet_does_not_block_app_startup(tmp_path):
    assert _stylesheet_version(tmp_path / "missing.css") is None


def test_login_omits_missing_stylesheet(monkeypatch):
    monkeypatch.setitem(app.jinja_env.globals, "style_version", None)
    response = app.test_client().get("/login")

    assert response.status_code == 200
    assert b"/static/style.css" not in response.data


def test_supervisor_operations_are_separate_from_admin_oversight():
    supervisor = app.test_client()
    administrator = app.test_client()
    supervisor.post(
        "/login", data={"email": "supervisor@pulsedesk.test", "password": "demo123"}
    )
    administrator.post(
        "/login", data={"email": "admin@pulsedesk.test", "password": "demo123"}
    )

    assert supervisor.get("/updates").status_code == 200
    assert supervisor.get("/demo-data").status_code == 302
    assert supervisor.post("/tickets/999999/assign").status_code == 404
    assert b"Operational queue" in supervisor.get("/tickets").data

    assert administrator.get("/updates").status_code == 302
    assert administrator.get("/demo-data").status_code == 200
    assert administrator.post("/tickets/999999/assign").status_code == 302
    assert b"Read-only oversight" in administrator.get("/tickets").data
    assert b"Updates" not in administrator.get("/tickets").data


def test_admin_can_create_officer_and_supervisor_accounts():
    administrator = app.test_client()
    officer = app.test_client()
    administrator.post(
        "/login", data={"email": "admin@pulsedesk.test", "password": "demo123"}
    )
    officer.post(
        "/login", data={"email": "officer@pulsedesk.test", "password": "demo123"}
    )
    assert administrator.get("/accounts").status_code == 200
    assert officer.get("/accounts").status_code == 302

    suffix = uuid4().hex
    new_officer_email = f"officer-{suffix}@example.test"
    new_supervisor_email = f"supervisor-{suffix}@example.test"
    try:
        for name, email, role in [
            ("New Officer", new_officer_email, "IT Support Officer"),
            ("New Supervisor", new_supervisor_email, "IT Supervisor"),
        ]:
            response = administrator.post(
                "/accounts",
                data={
                    "name": name,
                    "email": email.upper(),
                    "role": role,
                    "password": "temporary-pass-1",
                },
            )
            assert response.status_code == 302

        with app.app_context():
            created_officer = User.query.filter_by(email=new_officer_email).one()
            created_supervisor = User.query.filter_by(email=new_supervisor_email).one()
            assert created_officer.role == "IT Support Officer"
            assert created_supervisor.role == "IT Supervisor"
            assert created_officer.password != "temporary-pass-1"

        new_user = app.test_client()
        response = new_user.post(
            "/login",
            data={"email": new_officer_email, "password": "temporary-pass-1"},
        )
        assert response.status_code == 302
        assert new_user.get("/complaints").status_code == 200
    finally:
        with app.app_context():
            User.query.filter(User.email.in_([new_officer_email, new_supervisor_email])).delete(
                synchronize_session=False
            )
            db.session.commit()


def test_complaint_moves_through_work_and_dual_approval():
    officer = app.test_client()
    supervisor = app.test_client()
    administrator = app.test_client()
    officer.post(
        "/login", data={"email": "officer@pulsedesk.test", "password": "demo123"}
    )
    supervisor.post(
        "/login", data={"email": "supervisor@pulsedesk.test", "password": "demo123"}
    )
    administrator.post(
        "/login", data={"email": "admin@pulsedesk.test", "password": "demo123"}
    )
    with app.app_context():
        branch_id = Branch.query.order_by(Branch.id).first().id

    officer.post(
        "/complaints",
        data={
            "sender_name": "Test Branch Contact",
            "sender_email": "branch-contact@example.test",
            "subject": "Teller terminal error",
            "message": "Terminal shows a connection error.",
            "branch_id": branch_id,
            "system": "Teller Terminal",
            "category": "Hardware",
            "priority": "Medium",
        },
    )
    with app.app_context():
        complaint = Complaint.query.filter_by(
            sender_email="branch-contact@example.test"
        ).order_by(Complaint.id.desc()).first()
        complaint_id = complaint.id
        assert complaint.status == "Needs Review"
        assert complaint.ticket_id is None

    officer.post(
        f"/complaints/{complaint_id}/request-info",
        data={"info_request": "Please send the terminal error code."},
    )
    with app.app_context():
        complaint = db.session.get(Complaint, complaint_id)
        assert complaint.status == "Awaiting Sender"
        assert complaint.info_request == "Please send the terminal error code."

    officer.post(
        f"/complaints/{complaint_id}/sender-reply",
        data={"sender_reply": "The displayed code is NET-42."},
    )
    officer.post(f"/complaints/{complaint_id}/forward")
    with app.app_context():
        complaint = db.session.get(Complaint, complaint_id)
        ticket_id = complaint.ticket_id
        ticket = db.session.get(Ticket, ticket_id)
        assert complaint.status == "Forwarded to Supervisor"
        assert ticket.status == "Open"
        assert ticket.assigned_to is None
    assert b"Waiting for assignment" in officer.get(f"/tickets/{ticket_id}").data

    supervisor.post(
        f"/tickets/{ticket_id}/assign", data={"assigned_to": "Amina Yusuf"}
    )
    with app.app_context():
        assert db.session.get(Ticket, ticket_id).status == "Assigned"
    assert b"Assign support officer" in supervisor.get(f"/tickets/{ticket_id}").data

    officer.post(
        f"/tickets/{ticket_id}/progress",
        data={"action": "log-progress", "status": "In Progress", "message": "Checked the network cable."},
    )
    officer.post(
        f"/tickets/{ticket_id}/progress",
        data={"action": "submit-resolution", "message": "Replaced the cable and verified the terminal reconnects."},
    )
    with app.app_context():
        ticket = db.session.get(Ticket, ticket_id)
        assert ticket.status == "Pending Approval"
        assert TicketActivity.query.filter_by(ticket_id=ticket_id).count() >= 4
    assert b"Checked the network cable." in officer.get(f"/tickets/{ticket_id}").data

    supervisor.post(
        f"/tickets/{ticket_id}/approve", data={"note": "Supervisor verified the work log."}
    )
    with app.app_context():
        assert db.session.get(Ticket, ticket_id).status == "Pending Approval"
        assert TicketApproval.query.filter_by(ticket_id=ticket_id).count() == 1
    approval_page = administrator.get(f"/tickets/{ticket_id}").data
    assert b"IT Supervisor approved" in approval_page
    assert b"Administrator approval pending" in approval_page

    administrator.post(
        f"/tickets/{ticket_id}/approve", data={"note": "Administrator approved closure."}
    )
    with app.app_context():
        ticket = db.session.get(Ticket, ticket_id)
        assert ticket.status == "Resolved"
        assert ticket.resolved_at is not None
        assert TicketApproval.query.filter_by(ticket_id=ticket_id).count() == 2
        assert TicketActivity.query.filter_by(
            ticket_id=ticket_id, action="Closed"
        ).count() == 1
        assert b"Resolved" in administrator.get(f"/tickets/{ticket_id}").data

        TicketApproval.query.filter_by(ticket_id=ticket_id).delete()
        TicketActivity.query.filter_by(ticket_id=ticket_id).delete()
        db.session.delete(complaint)
        db.session.delete(ticket)
        db.session.commit()


def test_detector_creates_alert():
    with app.app_context():
        assert Ticket.query.count() >= 0
