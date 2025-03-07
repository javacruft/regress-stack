# Copyright 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock

import pytest

import regress_stack.core.apt


@pytest.fixture
def mock_apt(monkeypatch):
    cache = {}
    apt = Mock(Cache=Mock(return_value=cache))

    monkeypatch.setattr("regress_stack.core.apt.apt", apt)
    yield apt


def test_get_cache(mock_apt):
    regress_stack.core.apt.APT_CACHE = None
    assert regress_stack.core.apt.get_cache() == mock_apt.Cache()
    assert regress_stack.core.apt.APT_CACHE == mock_apt.Cache()


def test_pkgs_installed(mock_apt):
    regress_stack.core.apt.APT_CACHE = None
    assert regress_stack.core.apt.pkgs_installed(["pkg"]) is False

    regress_stack.core.apt.APT_CACHE = None
    mock_apt.Cache()["pkg"] = Mock(is_installed=True)
    assert regress_stack.core.apt.pkgs_installed(["pkg"]) is True
