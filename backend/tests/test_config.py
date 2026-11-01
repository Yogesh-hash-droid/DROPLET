import ssl
from unittest.mock import patch

import pytest

from app.config import Settings


def test_local_database_configuration_has_no_tls_by_default():
    settings = Settings(_env_file=None)

    assert settings.MYSQL_PORT == 3306
    assert settings.MYSQL_SSL is False
    assert settings.sqlalchemy_connect_args == {}


def test_aiven_configuration_uses_verified_tls_context(tmp_path):
    ca_file = tmp_path / "aiven-ca.pem"
    ca_file.write_text("placeholder", encoding="ascii")
    settings = Settings(
        _env_file=None,
        MYSQL_HOST="aiven.example",
        MYSQL_PORT=15444,
        MYSQL_USER="avnadmin",
        MYSQL_PASSWORD="not-used-in-output",
        MYSQL_DATABASE="defaultdb",
        MYSQL_SSL=True,
        MYSQL_SSL_CA=str(ca_file),
    )

    assert settings.MYSQL_PORT == 15444
    assert settings.sqlalchemy_database_url.endswith("@aiven.example:15444/defaultdb")
    context = ssl.create_default_context()
    with patch("app.config.ssl.create_default_context", return_value=context):
        connect_args = settings.sqlalchemy_connect_args
    assert connect_args["ssl"] is context
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_missing_tls_ca_is_reported_before_connection():
    settings = Settings(
        _env_file=None,
        MYSQL_SSL=True,
        MYSQL_SSL_CA="C:/does-not-exist/aiven-ca.pem",
    )

    with pytest.raises(ValueError, match="MYSQL_SSL_CA"):
        settings.sqlalchemy_connect_args
