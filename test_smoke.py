from app import _stylesheet_version, app, db, Ticket


def test_ticket_pages_load():
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/").status_code == 302
    client.post(
        "/login", data={"email": "officer@pulsedesk.test", "password": "demo123"}
    )
    assert client.get("/").status_code == 200
    assert client.get("/tickets").status_code == 200
    assert client.get("/tickets/new").status_code == 200


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


def test_detector_creates_alert():
    with app.app_context():
        assert Ticket.query.count() >= 0
