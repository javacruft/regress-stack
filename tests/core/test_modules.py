# Copyright 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import Mock, patch

import networkx as nx
import pytest

from regress_stack.core.modules import ModuleComp, build_dependency_graph, filter_graph


@pytest.fixture
def mock_modules():
    mock_mod1 = Mock()
    mock_mod1.name = "mod1"
    mock_mod1.__name__ = "regress_stack.modules.mod1"
    mock_mod1.__file__ = "/fake/path/mod1.py"
    mock_mod1.DEPENDENCIES = set()
    mock_mod1.OPTIONAL_DEPENDENCIES = set()
    mock_mod1.PACKAGES = ["pkg1"]

    mock_mod2 = Mock()
    mock_mod2.name = "mod2"
    mock_mod2.__name__ = "regress_stack.modules.mod2"
    mock_mod2.__file__ = "/fake/path/mod2.py"
    mock_mod2.DEPENDENCIES = {mock_mod1}
    mock_mod2.OPTIONAL_DEPENDENCIES = set()
    mock_mod2.PACKAGES = ["pkg2"]

    mock_mod3 = Mock()
    mock_mod3.name = "mod3"
    mock_mod3.__name__ = "regress_stack.modules.mod3"
    mock_mod3.__file__ = "/fake/path/mod3.py"
    mock_mod3.DEPENDENCIES = set()
    mock_mod3.OPTIONAL_DEPENDENCIES = {mock_mod1}
    mock_mod3.PACKAGES = ["pkg3"]

    mock_modules_mod = Mock()
    mock_modules_mod.__path__ = ["/fake/path"]
    mock_modules_mod.__package__ = "regress_stack.modules"
    mock_modules_mod.mod1 = mock_mod1
    mock_modules_mod.mod2 = mock_mod2
    mock_modules_mod.mod3 = mock_mod3

    return mock_modules_mod


@patch("regress_stack.core.modules.pkgutil.iter_modules")
@patch("regress_stack.core.modules.load_module")
@patch("regress_stack.core.modules.apt.pkgs_installed")
def test_build_dependency_graph(
    mock_pkgs_installed, mock_load_module, mock_iter_modules, mock_modules
):
    mock_iter_modules.return_value = [
        mock_modules.mod1,
        mock_modules.mod2,
        mock_modules.mod3,
    ]

    mock_load_module.side_effect = lambda name, path: getattr(
        mock_modules, name.rsplit(".", 1)[1]
    )
    mock_pkgs_installed.return_value = True

    graph = build_dependency_graph(mock_modules)

    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2

    mod1 = ModuleComp("regress_stack.modules.mod1", mock_modules.mod1)
    mod2 = ModuleComp("regress_stack.modules.mod2", mock_modules.mod2)
    mod3 = ModuleComp("regress_stack.modules.mod3", mock_modules.mod3)

    assert graph.has_node(mod1)
    assert graph.has_node(mod2)
    assert graph.has_node(mod3)

    assert graph.nodes[mod1]["installed"] is True
    assert graph.nodes[mod2]["installed"] is True
    assert graph.nodes[mod3]["installed"] is True

    assert graph.has_edge(mod1, mod2)
    assert graph.has_edge(mod1, mod3)
    assert not graph.has_edge(mod2, mod3)

    assert graph[mod1][mod2]["optional"] is False
    assert graph[mod1][mod3]["optional"] is True


@patch("regress_stack.core.modules.pkgutil.iter_modules")
@patch("regress_stack.core.modules.load_module")
@patch("regress_stack.core.modules.apt.pkgs_installed")
def test_build_dependency_graph_missing_packages(
    mock_pkgs_installed, mock_load_module, mock_iter_modules, mock_modules
):
    mock_iter_modules.return_value = [
        mock_modules.mod1,
        mock_modules.mod2,
        mock_modules.mod3,
    ]

    mock_load_module.side_effect = lambda name, path: getattr(
        mock_modules, name.rsplit(".", 1)[1]
    )
    mock_pkgs_installed.side_effect = lambda pkgs: pkgs != ["pkg1"]

    graph = build_dependency_graph(mock_modules)

    assert isinstance(graph, nx.DiGraph)
    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2

    mod1 = ModuleComp("regress_stack.modules.mod1", mock_modules.mod1)
    mod2 = ModuleComp("regress_stack.modules.mod2", mock_modules.mod2)
    mod3 = ModuleComp("regress_stack.modules.mod3", mock_modules.mod3)

    assert graph.has_node(mod1)
    assert graph.has_node(mod2)
    assert graph.has_node(mod3)

    assert graph.nodes[mod1]["installed"] is False
    assert graph.nodes[mod2]["installed"] is True
    assert graph.nodes[mod3]["installed"] is True


def test_filter_graph_all_installed(mock_modules):
    nodes = {
        "mysql": {"installed": True},
        "keystone": {"installed": True},
        "rabbitmq": {"installed": True},
        "glance": {"installed": True},
    }
    edges = [
        ("mysql", "keystone", {"optional": False}),
        ("mysql", "glance", {"optional": False}),
        ("keystone", "glance", {"optional": False}),
    ]
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes.items())
    graph.add_edges_from(edges)
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 3
    filtered_graph = filter_graph(graph)

    assert isinstance(filtered_graph, nx.DiGraph)
    assert len(filtered_graph.nodes) == len(graph.nodes)
    assert len(filtered_graph.edges) == len(graph.edges)


def test_filter_graph_some_uninstalled():
    """Tests the following graph:

    mysql -> keystone
    mysql -> glance
    keystone -> glance
    rabbitmq

    Where mysql is not installed, rabbitmq, keystone and glance are installed.

    Expected result is the following graph:
    rabbitmq
    """
    nodes = {
        "mysql": {"installed": False},
        "keystone": {"installed": True},
        "rabbitmq": {"installed": True},
        "glance": {"installed": True},
    }
    edges = [
        ("mysql", "keystone", {"optional": False}),
        ("mysql", "glance", {"optional": False}),
        ("keystone", "glance", {"optional": False}),
    ]
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes.items())
    graph.add_edges_from(edges)
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 3
    filtered_graph = filter_graph(graph)

    assert isinstance(filtered_graph, nx.DiGraph)
    assert len(filtered_graph.nodes) == 1
    assert len(filtered_graph.edges) == 0
    assert graph.has_node("rabbitmq")


def test_filter_graph_optional_dependency_missing():
    """Test the following graph:

    mysql -> keystone
    mysql -> glance
    keystone -> optional -> glance

    Where keystone is not installed, mysql, rabbitmq, and glance are installed.

    Expected result is the following graph:
    mysql -> glance
    rabbitmq
    """
    nodes = {
        "mysql": {"installed": True},
        "keystone": {"installed": False},
        "rabbitmq": {"installed": True},
        "glance": {"installed": True},
    }
    edges = [
        ("mysql", "keystone", {"optional": False}),
        ("mysql", "glance", {"optional": False}),
        ("keystone", "glance", {"optional": True}),
    ]
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes.items())
    graph.add_edges_from(edges)
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 3
    filtered_graph = filter_graph(graph)

    assert isinstance(filtered_graph, nx.DiGraph)
    assert len(filtered_graph.nodes) == 3
    assert len(filtered_graph.edges) == 1
    assert graph.has_node("rabbitmq")
    assert graph.has_node("mysql")
    assert graph.has_node("glance")
    assert graph.has_edge("mysql", "glance")
