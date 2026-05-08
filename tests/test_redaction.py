from src.app.redaction import redact_sensitive_data


def test_redaction_handles_snake_case_api_keys():
    payload = {
        "api_key": "secret-1",
        "x_api_key": "secret-2",
        "nested": {"x_api_key": "secret-3"},
        "safe": "visible",
    }

    redacted = redact_sensitive_data(payload)

    assert redacted["api_key"] == "<redacted>"
    assert redacted["x_api_key"] == "<redacted>"
    assert redacted["nested"]["x_api_key"] == "<redacted>"
    assert redacted["safe"] == "visible"
