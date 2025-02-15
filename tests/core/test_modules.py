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
    return module


@pytest.fixture
def mock_apt(monkeypatch):
    cache = {}
    apt = Mock(Cache=Mock(return_value=cache))

    monkeypatch.setattr("regress_stack.core.modules.apt", apt)
    yield apt


@pytest.fixture
def mock_modulefinder(monkeypatch):
    mf = Mock()
    modulefinder = Mock(ModuleFinder=Mock(return_value=mf))
    monkeypatch.setattr("regress_stack.core.modules.modulefinder", modulefinder)

    @contextlib.contextmanager
    def mock_modules(names: typing.Sequence[str]):
        mf.modules = {name: name + ".py" for name in names}
        yield

    return mock_modules


def test_build_dependency_graph_empty(mock_module):
    graph = build_dependency_graph(mock_module)
    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 1
    assert len(graph.edges) == 0


def test_build_dependency_graph_with_missing_dependencies(
    monkeypatch, mock_module, mock_apt, mock_modulefinder
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

    with mock_modulefinder(["dep1"]):
        graph = build_dependency_graph(mock_module)
    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 1
    assert len(graph.edges) == 0


def test_build_dependency_graph(monkeypatch, mock_module, mock_apt, mock_modulefinder):
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

    mock_apt.Cache()["dep"] = Mock(is_installed=True)

    with mock_modulefinder(["dep1"]):
        graph = build_dependency_graph(mock_module)
    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
