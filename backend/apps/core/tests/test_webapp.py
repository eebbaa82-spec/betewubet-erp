import pytest
from django.test import override_settings


@pytest.mark.django_db
def test_pages_get_the_web_app(client, tmp_path):
    (tmp_path / "index.html").write_text("<div id=root></div>")
    with override_settings(FRONTEND_DIST=str(tmp_path)):
        r = client.get("/work-orders/12")
        assert r.status_code == 200 and b"root" in r.content
        assert "csrftoken" in r.cookies
    assert client.get("/api/nothing-here/").status_code in (401, 403, 404)


@pytest.mark.django_db
def test_missing_build_says_how_to_fix(client, tmp_path):
    with override_settings(FRONTEND_DIST=str(tmp_path)):
        r = client.get("/finance")
    assert r.status_code == 404 and b"npm run build" in r.content
