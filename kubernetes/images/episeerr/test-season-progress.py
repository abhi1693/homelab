#!/usr/bin/env python3
"""Behavioral checks for the patched season prefetch selector."""

import ast
import os
from pathlib import Path
from typing import List, Optional


class Logger:
    def info(self, _message):
        pass

    def error(self, _message):
        pass


source = Path("/app/media_processor.py").read_text(encoding="utf-8")
tree = ast.parse(source)
function = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "fetch_next_episodes_dropdown"
)
module = ast.Module(body=[function], type_ignores=[])

seasons = {}


def get_episode_details(_series_id, season_number):
    return seasons.get(season_number, [])


namespace = {
    "get_episode_details": get_episode_details,
    "fetch_all_episodes": lambda _series_id: [],
    "logger": Logger(),
}
exec(compile(module, "media_processor.py", "exec"), namespace)
select = namespace["fetch_next_episodes_dropdown"]


def episodes(season, count, *, monitored=False):
    return [
        {
            "id": season * 100 + number,
            "episodeNumber": number,
            "monitored": monitored,
        }
        for number in range(1, count + 1)
    ]


seasons.update({1: episodes(1, 10), 2: episodes(2, 10)})
before = select(1, 1, 3, "seasons", 1, 49.0, 25.0)
assert all(identifier < 200 for identifier in before), before

at_threshold = select(1, 1, 3, "seasons", 1, 50.0, 25.0)
assert set(range(201, 211)).issubset(at_threshold), at_threshold

seasons[2] = episodes(2, 10, monitored=True)
already_requested = select(1, 1, 4, "seasons", 1, 50.0, 25.0)
assert all(identifier < 200 for identifier in already_requested), already_requested

seasons.clear()
seasons.update({1: episodes(1, 8), 2: episodes(2, 8)})
quarter_complete = select(1, 1, 2, "seasons", 1, 100.0, 25.0)
assert set(range(201, 209)).issubset(quarter_complete), quarter_complete

legacy_finale = select(1, 1, 8, "seasons", 1)
assert set(range(201, 209)).issubset(legacy_finale), legacy_finale

print("Season-progress behavioral tests passed")

integration_source = Path("/app/integrations/jellyfin.py").read_text(
    encoding="utf-8"
)
integration_tree = ast.parse(integration_source)
jellyfin_class = next(
    node
    for node in integration_tree.body
    if isinstance(node, ast.ClassDef) and node.name == "JellyfinIntegration"
)
progress_function = next(
    node
    for node in jellyfin_class.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "calculate_season_progress"
)
progress_function.decorator_list = []
progress_module = ast.Module(body=[progress_function], type_ignores=[])
progress_namespace = {}
exec(compile(progress_module, "integrations/jellyfin.py", "exec"), progress_namespace)
calculate = progress_namespace["calculate_season_progress"]
assert calculate((2, 10), 50.0) == 25.0
assert calculate((1, 8), 100.0) == 25.0

print("Jellyfin aggregate-progress tests passed")

path_function = next(
    node
    for node in jellyfin_class.body
    if isinstance(node, ast.FunctionDef) and node.name == "path_is_allowed"
)
path_function.decorator_list = []
path_module = ast.Module(body=[path_function], type_ignores=[])
path_namespace = {"os": __import__("os"), "Optional": Optional, "List": List}
exec(compile(path_module, "integrations/jellyfin.py", "exec"), path_namespace)
path_is_allowed = path_namespace["path_is_allowed"]
assert path_is_allowed("/media/tv/Andor/episode.mkv", ["/media/tv"])
assert path_is_allowed("/media/tv", ["/media/tv"])
assert not path_is_allowed("/media/tv-anime/episode.mkv", ["/media/tv"])
assert not path_is_allowed("/media/anime/episode.mkv", ["/media/tv"])
assert not path_is_allowed(None, ["/media/tv"])

print("Jellyfin TV-library allowlist tests passed")


class Response:
    ok = True
    status_code = 200

    def __init__(self, path):
        self.path = path

    def json(self):
        return {"Path": self.path}


class HTTP:
    def __init__(self):
        self.paths = {}
        self.last_params = None

    def get(self, url, **kwargs):
        self.last_params = kwargs.get("params")
        return Response(self.paths[url.rsplit("/", 1)[-1]])


http = HTTP()
episode_filter = next(
    node
    for node in jellyfin_class.body
    if isinstance(node, ast.FunctionDef) and node.name == "is_allowed_episode"
)
filter_class = ast.ClassDef(
    name="FilterProbe",
    bases=[],
    keywords=[],
    body=[path_function, episode_filter],
    decorator_list=[],
)
filter_module = ast.Module(body=[filter_class], type_ignores=[])
filter_module = ast.fix_missing_locations(filter_module)
filter_namespace = {
    "os": os,
    "Optional": Optional,
    "List": List,
    "Dict": dict,
    "logger": Logger(),
    "http": http,
}
exec(compile(filter_module, "integrations/jellyfin.py", "exec"), filter_namespace)
FilterProbe = filter_namespace["FilterProbe"]
FilterProbe.path_is_allowed = staticmethod(path_is_allowed)
FilterProbe.get_config = lambda self: {"url": "http://jellyfin", "api_key": "key"}
FilterProbe._resolve_user_id = lambda self, _config: "user-guid"
http.paths = {"tv-item": "/media/tv/Andor/episode.mkv", "anime-item": None}
old_allowed_prefixes = os.environ.get("JELLYFIN_ALLOWED_PATH_PREFIXES")
os.environ["JELLYFIN_ALLOWED_PATH_PREFIXES"] = "/media/tv"
try:
    probe = FilterProbe()
    assert probe.is_allowed_episode({"ItemId": "tv-item"})
    assert http.last_params == {"Fields": "Path", "UserId": "user-guid"}
    assert not probe.is_allowed_episode({"ItemId": "anime-item"})
finally:
    if old_allowed_prefixes is None:
        os.environ.pop("JELLYFIN_ALLOWED_PATH_PREFIXES", None)
    else:
        os.environ["JELLYFIN_ALLOWED_PATH_PREFIXES"] = old_allowed_prefixes

print("Jellyfin webhook item-resolution tests passed")


class SearchResponse:
    ok = True
    text = ""


class SearchHTTP:
    def __init__(self):
        self.commands = []

    def post(self, _url, *, json, headers):
        self.commands.append(json)
        return SearchResponse()


search_http = SearchHTTP()
search_function = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "trigger_episode_search_in_sonarr"
)
search_module = ast.Module(body=[search_function], type_ignores=[])
search_namespace = {
    "SONARR_URL": "http://sonarr",
    "SONARR_API_KEY": "key",
    "logger": Logger(),
    "http": search_http,
    "get_episode_details_by_id": lambda episode_id: {
        "id": episode_id,
        "seasonNumber": 1 if episode_id < 200 else 2,
        "episodeNumber": episode_id % 100,
    },
}
exec(compile(search_module, "media_processor.py", "exec"), search_namespace)
search_namespace["trigger_episode_search_in_sonarr"](
    [101, 102, 201, 202],
    series_id=7,
    series_title=None,
    get_type="seasons",
)
assert search_http.commands == [
    {"name": "SeasonSearch", "seriesId": 7, "seasonNumber": 1},
    {"name": "SeasonSearch", "seriesId": 7, "seasonNumber": 2},
]

operation_order = []
dispatch_function = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "monitor_or_search_episodes"
)
dispatch_module = ast.Module(body=[dispatch_function], type_ignores=[])
dispatch_namespace = {
    "logger": Logger(),
    "monitor_episodes": lambda ids, monitor: operation_order.append(
        ("monitor", list(ids), monitor)
    ),
    "trigger_episode_search_in_sonarr": lambda ids, *args: operation_order.append(
        ("search", list(ids))
    ),
}
exec(compile(dispatch_module, "media_processor.py", "exec"), dispatch_namespace)
dispatch_namespace["monitor_or_search_episodes"](
    [201, 202], "search", series_id=7, series_title="Series", get_type="seasons"
)
assert operation_order == [
    ("monitor", [201, 202], True),
    ("search", [201, 202]),
]

print("Sonarr monitor-before-multi-season-search tests passed")
