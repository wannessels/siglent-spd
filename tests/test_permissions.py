"""Tests for permission and safety limit helpers."""

import os
from unittest.mock import patch

from siglent_spd_mcp.server import _check_current, _check_voltage, _get_perm, _require_write


def test_default_permission_is_readonly():
    with patch.dict(os.environ, {}, clear=True):
        assert _get_perm("CH1") == "readonly"


def test_readwrite_permission():
    with patch.dict(os.environ, {"CH1_PERM": "readwrite"}):
        assert _get_perm("CH1") == "readwrite"


def test_invalid_permission_defaults_readonly():
    with patch.dict(os.environ, {"CH1_PERM": "bogus"}):
        assert _get_perm("CH1") == "readonly"


def test_require_write_denied_when_readonly():
    with patch.dict(os.environ, {}, clear=True):
        err = _require_write("CH1")
        assert err is not None
        assert "DENIED" in err


def test_require_write_allowed_when_readwrite():
    with patch.dict(os.environ, {"CH1_PERM": "readwrite"}):
        assert _require_write("CH1") is None


def test_voltage_within_limit():
    with patch.dict(os.environ, {"CH1_MAX_VOLTAGE": "5.0"}):
        assert _check_voltage("CH1", 3.3) is None


def test_voltage_exceeds_limit():
    with patch.dict(os.environ, {"CH1_MAX_VOLTAGE": "5.0"}):
        err = _check_voltage("CH1", 6.0)
        assert err is not None
        assert "SAFETY" in err


def test_voltage_no_limit_configured():
    with patch.dict(os.environ, {}, clear=True):
        assert _check_voltage("CH1", 30.0) is None


def test_current_within_limit():
    with patch.dict(os.environ, {"CH1_MAX_CURRENT": "1.0"}):
        assert _check_current("CH1", 0.5) is None


def test_current_exceeds_limit():
    with patch.dict(os.environ, {"CH1_MAX_CURRENT": "1.0"}):
        err = _check_current("CH1", 2.0)
        assert err is not None
        assert "SAFETY" in err
