import pytest


@pytest.mark.integration
def test_integration_placeholder():
    pytest.skip("Run the PostgreSQL integration suite in CI or with local infrastructure")
