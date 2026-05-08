import pytest
from pydantic import ValidationError

from src.app.schemas import NotificationCreate


def test_public_https_vendor_url_is_allowed():
    payload = NotificationCreate(target_url="https://vendor.example.test/webhook")

    assert str(payload.target_url) == "https://vendor.example.test/webhook"


@pytest.mark.parametrize(
    "target_url",
    [
        "http://localhost./internal",
        "http://foo.localhost./internal",
        "http://127.0.0.1:8000/internal",
        "http://localhost:8000/internal",
        "http://10.0.0.5/webhook",
        "http://172.16.0.2/webhook",
        "http://192.168.1.10/webhook",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_internal_or_metadata_target_urls_are_rejected(target_url):
    with pytest.raises(ValidationError) as exc_info:
        NotificationCreate(target_url=target_url)

    assert "target_url is not allowed" in str(exc_info.value)
