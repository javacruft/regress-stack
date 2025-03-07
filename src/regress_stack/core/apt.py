# Copyright 2025 - Canonical Ltd
# SPDX-License-Identifier: Apache-2.0

import typing

import apt

APT_CACHE: type(apt.cache.Cache) = None


def get_cache() -> apt.cache.Cache:
    global APT_CACHE

    if APT_CACHE is None:
        APT_CACHE = apt.Cache()

    return APT_CACHE


def pkgs_installed(pkgs: typing.List[str]) -> bool:
    apt_cache = get_cache()

    try:
        return all([apt_cache[pkg].is_installed for pkg in pkgs])
    except KeyError:
        return False
