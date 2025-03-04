import contextlib
import types
import typing
from unittest.mock import Mock

import networkx as nx
import pytest

from regress_stack.core.modules import build_dependency_graph


@pytest.fixture
def mock_module():
    module = types.ModuleType("mock_module")
    module.__path__ = ["package/"]
    module.__package__ = "package"
    module.__file__ = "./mock_module"
    module.utils = types.ModuleType("utils")
    module.utils.__name__ = "utils"
    module.utils.__file__ = "./mock_module/utils"
    return module


@pytest.fixture
def mock_apt(monkeypatch):
    apt = Mock(pkgs_installed=Mock(return_value=False))

    monkeypatch.setattr("regress_stack.core.modules.apt", apt)
    yield apt


def test_build_dependency_graph_empty(mock_module):
    graph = build_dependency_graph(mock_module)
    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 1
    assert len(graph.edges) == 0


def test_build_dependency_graph_with_missing_dependencies(
    monkeypatch, mock_module, mock_apt
):
    def mock_iter_modules(path):
        return [
            types.SimpleNamespace(
                name="dep1", module_finder=types.SimpleNamespace(path="./mock_module")
            )
        ]

    def mock_load_module(name, path):
        module = types.ModuleType(name)
        module.__file__ = path
        module.PACKAGES = ["nonexistent_package"]
        return module

    monkeypatch.setattr("pkgutil.iter_modules", mock_iter_modules)
    monkeypatch.setattr("regress_stack.core.modules.load_module", mock_load_module)

    graph = build_dependency_graph(mock_module)
    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 1
    assert len(graph.edges) == 0


def test_build_dependency_graph(monkeypatch, mock_module, mock_apt):
    def mock_iter_modules(path):
        return [
            types.SimpleNamespace(
                name="dep1", module_finder=types.SimpleNamespace(path="./mock_module")
            )
        ]

    def mock_load_module(name, path):
        module = types.ModuleType(name)
        module.__file__ = path
        module.PACKAGES = ["dep"]
        return module

    monkeypatch.setattr("pkgutil.iter_modules", mock_iter_modules)
    monkeypatch.setattr("regress_stack.core.modules.load_module", mock_load_module)

    mock_apt.pkgs_installed = Mock(return_value=True)

    graph = build_dependency_graph(mock_module)
    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
