from conftest_cassettes import scrub_response_headers


def _vcr_response(headers):
    # The shape vcrpy hands to before_record_response.
    return {
        "status": {"code": 200, "message": "OK"},
        "headers": headers,
        "body": {"string": b'{"ok": true}'},
    }


def test_scrub_drops_account_identifier_headers_and_keeps_the_rest():
    response = _vcr_response(
        {
            "anthropic-organization-id": ["0f0f0f0f-org"],
            "anthropic-workspace-id": ["wrkspc_123"],
            "Request-Id": ["req_abc"],
            "cf-ray": ["8a8a8a8a-SJC"],
            "x-goog-project-id": ["123456789"],
            "X-Goog-Quota-Project": ["my-project"],
            "content-type": ["application/json"],
            "anthropic-ratelimit-requests-limit": ["50"],
            "x-goog-api-client": ["genai-py"],
        }
    )
    scrubbed = scrub_response_headers(response)
    assert scrubbed is not None
    assert scrubbed["headers"] == {
        "content-type": ["application/json"],
        "anthropic-ratelimit-requests-limit": ["50"],
        "x-goog-api-client": ["genai-py"],
    }
    assert scrubbed["status"] == {"code": 200, "message": "OK"}
    assert scrubbed["body"] == {"string": b'{"ok": true}'}


def test_scrub_tolerates_a_response_without_headers():
    response = {"status": {"code": 204, "message": "No Content"}, "body": {"string": b""}}
    assert scrub_response_headers(response) == response
