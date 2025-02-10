import importlib
import importlib.util
import logging
import modulefinder
import os
import pathlib
import pkgutil
import types
import typing

import apt
import networkx as nx

LOG = logging.getLogger(__name__)
_MOD_REGISTRY: typing.MutableMapping[str, types.ModuleType] = {}


def load_module(name: str, path: str):
    if name in _MOD_REGISTRY:
        return _MOD_REGISTRY[name]
    spec = importlib.util.find_spec(name, path)
    if spec is None:
        raise RuntimeError(f"Module {name} not found!")
    module_loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module_loaded)
    _MOD_REGISTRY[name] = module_loaded
    LOG.debug("Loaded module %r from %r", name, path)
    return module_loaded


def modules() -> typing.List[str]:
    return list(module.rsplit(".")[-1] for module in _MOD_REGISTRY.keys())


class ModuleComp:
    name: str
    module: types.ModuleType

    def __init__(self, name: str, module: types.ModuleType) -> None:
        self.name = name
        self.module = module

    def __hash__(self) -> int:
        return hash(self.name) ^ hash(self.module.__file__)

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, ModuleComp):
            return False
        if self.name == value.name and self.module.__file__ == value.module.__file__:
            return True
        return False

    def __str__(self) -> str:
        return self.name

    def __lt__(self, other: "ModuleComp") -> bool:
        return self.name < other.name

    def __repr__(self) -> str:
        return f"ModuleComp(name={self.name}, file={self.module.__file__})"


def get_dependencies(
    search_path: str, module_info: pkgutil.ModuleInfo, package: str
) -> typing.Set[ModuleComp]:
    """Find dependencies of a given module."""
    finder = modulefinder.ModuleFinder(path=[search_path])
    finder.run_script(
        os.path.join(module_info.module_finder.path, f"{module_info.name}.py")
    )

    dependencies = {
        ModuleComp(name, load_module(name, module.__file__))
        for name, module in finder.modules.items()
        if name.startswith(package + ".")
    }
    return dependencies


def build_dependency_graph(modules_mod: types.ModuleType) -> nx.DiGraph:
    """Build a directed graph of dependencies."""
    modules_dir = pathlib.Path(modules_mod.__path__[0])
    package = str(modules_mod.__package__)
    modules = list(pkgutil.iter_modules([str(modules_dir)]))
    graph: nx.DiGraph[ModuleComp] = nx.DiGraph()

    cache = apt.Cache()

    root = ModuleComp(package, modules_mod)
    graph.add_node(root)

    search_path = modules_dir.parent.parent.absolute()
    banned = set()

    for module in modules:
        canonical_name = package + "." + module.name
        module_loaded = load_module(canonical_name, module.module_finder.path)
        missing_deps = set()
        mod = ModuleComp(
            canonical_name,
            module_loaded,
        )
        if hasattr(module_loaded, "PACKAGES"):
            for pkg_name in module_loaded.PACKAGES:
                pkg = cache.get(pkg_name)
                if not pkg or not pkg.is_installed:
                    missing_deps.add(pkg_name)
            # Actually handle banned nodes
            if missing_deps:
                LOG.debug(
                    "Skipping module %r due to missing dependencies: %r",
                    module.name,
                    missing_deps,
                )
                banned.add(mod)
                continue

        dependencies = get_dependencies(str(search_path), module, package)
        if dependencies.intersection(banned):
            LOG.debug(
                "Skipping module %r due to missing dependencies: %r",
                module.name,
                dependencies.intersection(banned),
            )
            banned.add(mod)
            continue
        graph.add_node(mod)
        graph.add_edge(root, mod)
        for dep in dependencies:
            graph.add_edge(dep, mod)

    # Remove banned modules and their dependents
    to_remove = set()
    for banned_node in banned:
        if banned_node in graph:
            to_remove.add(banned_node)
            to_remove.update(nx.descendants(graph, banned_node))

    graph.remove_nodes_from(to_remove)  # Remove all in one operation
    LOG.debug("Removed nodes due to missing dependencies: %r", to_remove)
    return graph


def get_execution_order(
    modules_mod: types.ModuleType, target=None
) -> typing.List[ModuleComp]:
    """Determine the execution order of modules based on dependencies."""
    LOG.debug("Building dependency graph from %r...", modules_mod.__name__)
    graph = build_dependency_graph(modules_mod)

    if not nx.is_directed_acyclic_graph(graph):
        raise RuntimeError("Circular dependency detected!")

    order = list(nx.lexicographical_topological_sort(graph))
    if not target:
        return order

    root = ModuleComp(str(modules_mod.__package__), modules_mod)

    start_node = root

    end_node = None
    for mod in order:
        if mod.name.rsplit(".")[-1] == target:
            end_node = mod
            break
    else:
        raise RuntimeError(f"Target {target!r} not found!")

    paths = nx.all_simple_paths(graph, start_node, end_node)
    nodes_between_set = {node for path in paths for node in path}
    sg: nx.DiGraph[ModuleComp] = graph.subgraph(nodes_between_set)
    return list(nx.lexicographical_topological_sort(sg))
