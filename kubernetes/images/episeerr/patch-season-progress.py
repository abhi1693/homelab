#!/usr/bin/env python3
"""Patch Episeerr 4.0.5 with aggregate season-progress prefetching."""

from pathlib import Path


APP = Path("/app")


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = APP / relative_path
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(old)
    if occurrences != 1:
        raise RuntimeError(
            f"Expected one patch target in {relative_path}, found {occurrences}"
        )
    path.write_text(source.replace(old, new), encoding="utf-8")


replace_once(
    "integrations/jellyfin.py",
    """        # Otherwise check if username matches
        return username.lower() == configured_user.lower()
    # ==========================================
    # Polling Functions
""",
    """        # Otherwise check if username matches
        return username.lower() == configured_user.lower()

    @staticmethod
    def path_is_allowed(path: Optional[str], allowed_prefixes: List[str]) -> bool:
        \"\"\"Return whether a media path is inside an explicitly allowed root.\"\"\"
        if not path:
            return False
        normalized_path = os.path.normpath(path)
        return any(
            normalized_path == prefix
            or normalized_path.startswith(prefix + os.sep)
            for prefix in allowed_prefixes
        )

    def is_allowed_episode(self, item: Dict) -> bool:
        \"\"\"Fail closed unless an episode belongs to an allowed media root.\"\"\"
        configured_prefixes = os.getenv('JELLYFIN_ALLOWED_PATH_PREFIXES', '')
        allowed_prefixes = [
            os.path.normpath(prefix.strip())
            for prefix in configured_prefixes.split(',')
            if prefix.strip()
        ]
        if not allowed_prefixes:
            logger.error("JELLYFIN_ALLOWED_PATH_PREFIXES is empty; ignoring episode")
            return False

        path = item.get('Path')
        item_id = item.get('ItemId') or item.get('Id')
        if not path and item_id:
            config = self.get_config()
            if not config:
                return False
            try:
                user_id = self._resolve_user_id(config)
                if not user_id:
                    logger.warning(
                        f"Could not resolve Jellyfin user for item {item_id}"
                    )
                    return False
                response = http.get(
                    f"{config['url']}/Items/{item_id}",
                    headers={'X-Emby-Token': config['api_key']},
                    params={'Fields': 'Path', 'UserId': user_id},
                    timeout=10,
                )
                if response.ok:
                    path = response.json().get('Path')
                else:
                    logger.warning(
                        f"Could not resolve Jellyfin item {item_id}: "
                        f"HTTP {response.status_code}"
                    )
            except Exception as error:
                logger.warning(f"Could not resolve Jellyfin item {item_id}: {error}")

        allowed = self.path_is_allowed(path, allowed_prefixes)
        if not allowed:
            logger.info(
                "Ignoring Jellyfin episode outside allowed TV media roots"
            )
        return allowed
    # ==========================================
    # Polling Functions
""",
)

replace_once(
    "integrations/jellyfin.py",
    """            if not now_playing or now_playing.get('Type') != 'Episode':
                return None
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
            play_state = session.get('PlayState', {})
""",
    """            if not now_playing or now_playing.get('Type') != 'Episode':
                return None
            if not self.is_allowed_episode(now_playing):
                return None

            play_state = session.get('PlayState', {})
""",
)

replace_once(
    "integrations/jellyfin.py",
    """                method = config.get('method', 'polling')
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
                # ============================================================================
                # REAL-TIME MODE: PlaybackProgress
""",
    """                method = config.get('method', 'polling')

                if (
                    data.get('ItemType') == 'Episode'
                    and not integration.is_allowed_episode(data)
                ):
                    return jsonify({
                        'status': 'success',
                        'message': 'Episode outside allowed TV library',
                    }), 200

                # ============================================================================
                # REAL-TIME MODE: PlaybackProgress
""",
)

replace_once(
    "integrations/jellyfin.py",
    """    def should_trigger(self, progress: float, threshold: float) -> bool:
        \"\"\"Check if progress meets trigger threshold\"\"\"
        return progress >= float(threshold)\x20
\x20\x20\x20\x20
    def poll_session(self, session_id: str, initial_episode_info: Dict):
""",
    """    def should_trigger(self, progress: float, threshold: float) -> bool:
        \"\"\"Check if progress meets trigger threshold\"\"\"
        return progress >= float(threshold)

    def get_season_position(self, episode_info: Dict) -> Optional[tuple]:
        \"\"\"Return zero-based episode position and episode count for a season.\"\"\"
        try:
            from media_processor import get_episode_details, get_series_id

            series_id = get_series_id(episode_info['series_name'])
            if not series_id:
                return None
            episodes = sorted(
                get_episode_details(series_id, episode_info['season_number']),
                key=lambda item: item['episodeNumber'],
            )
            for position, episode in enumerate(episodes):
                if episode['episodeNumber'] == episode_info['episode_number']:
                    return position, len(episodes)
        except Exception as error:
            logger.warning(f\"Could not calculate Jellyfin season position: {error}\")
        return None

    @staticmethod
    def calculate_season_progress(position: tuple, episode_progress: float) -> float:
        \"\"\"Calculate aggregate season progress from an episode playback point.\"\"\"
        episodes_before, episode_count = position
        bounded_progress = max(0.0, min(float(episode_progress), 100.0))
        return ((episodes_before + bounded_progress / 100.0) / episode_count) * 100.0

    def poll_session(self, session_id: str, initial_episode_info: Dict):
""",
)

replace_once(
    "integrations/jellyfin.py",
    """        trigger_percentage = config.get('trigger_percentage', 50.0)
\x20\x20\x20\x20\x20\x20\x20\x20
        logger.info(f\"🔄 Starting Jellyfin polling for session {session_id}\")
        logger.info(f\"   📺 {initial_episode_info['series_name']} S{initial_episode_info['season_number']}E{initial_episode_info['episode_number']}\")
        logger.info(f\"   🎯 Will trigger at {trigger_percentage}% progress\")
""",
    """        trigger_percentage = config.get('trigger_percentage', 50.0)
        season_trigger_percentage = config.get('season_trigger_percentage')
        season_position = (
            self.get_season_position(initial_episode_info)
            if season_trigger_percentage is not None
            else None
        )

        logger.info(f\"🔄 Starting Jellyfin polling for session {session_id}\")
        logger.info(f\"   📺 {initial_episode_info['series_name']} S{initial_episode_info['season_number']}E{initial_episode_info['episode_number']}\")
        if season_position:
            logger.info(f\"   🎯 Will trigger at {season_trigger_percentage}% aggregate season progress\")
        else:
            logger.info(f\"   🎯 Will trigger at {trigger_percentage}% episode progress\")
""",
)

replace_once(
    "integrations/jellyfin.py",
    """                # Check if we should trigger processing
                if self.should_trigger(current_progress, trigger_percentage):
                    logger.info(f\"🎯 Trigger threshold reached! Processing at {current_progress:.1f}%\")
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
                    success = self.process_episode(current_episode_info)
""",
    """                # Prefer aggregate season progress when configured. The
                # per-episode threshold remains the compatibility fallback.
                season_progress = (
                    self.calculate_season_progress(season_position, current_progress)
                    if season_position
                    else None
                )
                threshold_reached = (
                    season_progress >= float(season_trigger_percentage)
                    if season_progress is not None
                    else self.should_trigger(current_progress, trigger_percentage)
                )
                if threshold_reached:
                    if season_progress is not None:
                        logger.info(
                            f\"🎯 Season threshold reached at {season_progress:.1f}% \"
                            f\"(episode progress {current_progress:.1f}%)\"
                        )
                    else:
                        logger.info(f\"🎯 Episode threshold reached at {current_progress:.1f}%\")

                    success = self.process_episode(current_episode_info)
""",
)

replace_once(
    "integrations/jellyfin.py",
    """                'source': 'jellyfin',
                'user': user_name
""",
    """                'source': 'jellyfin',
                'user': user_name,
                'progress_percent': float(progress),
""",
)

replace_once(
    "integrations/jellyfin.py",
    """                        trigger_percentage = float(config.get('trigger_percentage', 50.0))
                        if progress_percent >= trigger_percentage:
                            logger.info(f\"🎯 Processing on stop at {progress_percent:.1f}%\")

                            episode_info = {
""",
    """                        trigger_percentage = float(config.get('trigger_percentage', 50.0))
                        season_trigger_percentage = config.get('season_trigger_percentage')
                        stop_episode_info = {
                            'series_name': series_name,
                            'season_number': int(season),
                            'episode_number': int(episode),
                        }
                        season_position = (
                            integration.get_season_position(stop_episode_info)
                            if season_trigger_percentage is not None
                            else None
                        )
                        season_progress = (
                            integration.calculate_season_progress(
                                season_position, progress_percent
                            )
                            if season_position
                            else None
                        )
                        threshold_reached = (
                            season_progress >= float(season_trigger_percentage)
                            if season_progress is not None
                            else progress_percent >= trigger_percentage
                        )
                        if threshold_reached:
                            if season_progress is not None:
                                logger.info(
                                    f\"🎯 Processing on stop at {season_progress:.1f}% \"
                                    \"aggregate season progress\"
                                )
                            else:
                                logger.info(f\"🎯 Processing on stop at {progress_percent:.1f}%\")

                            episode_info = {
""",
)

replace_once(
    "media_processor.py",
    """    data = {"name": "EpisodeSearch", "episodeIds": episode_ids}
    response = http.post(url, json=data, headers=headers)

    episode = None
""",
    """    # Keep upstream's missing-file filter. A full missing season can use a
    # pack search; a partially downloaded season must search only missing IDs.
    episode = None
    search_commands = []
    individual_ids = []
    if get_type == 'seasons' and series_id and episodes is not None:
        details_by_id = {item['id']: item for item in episodes}
        by_season = {}
        for episode_id in episode_ids:
            details = details_by_id.get(episode_id)
            season_number = details.get('seasonNumber') if details else None
            if season_number is None:
                individual_ids.append(episode_id)
            else:
                by_season.setdefault(season_number, []).append(episode_id)
        for season_number, selected_ids in by_season.items():
            inventory = get_episode_details(series_id, season_number)
            all_ids = {item['id'] for item in inventory}
            if (all_ids and set(selected_ids) == all_ids
                    and not any(item.get('hasFile') for item in inventory)):
                search_commands.append({
                    "name": "SeasonSearch",
                    "seriesId": series_id,
                    "seasonNumber": season_number,
                })
            else:
                individual_ids.extend(selected_ids)
    else:
        individual_ids = episode_ids
    if individual_ids:
        search_commands.append({"name": "EpisodeSearch", "episodeIds": individual_ids})
    responses = [http.post(url, json=command, headers=headers) for command in search_commands]
    if not responses or any(not response.ok for response in responses):
        logger.error("Failed to send Sonarr search command(s)")
        return
    response = responses[-1]
""",
)


replace_once(
    "settings_db.py",
    """            base.update({
                'poll_interval': config.get('poll_interval', 900),
                'trigger_percentage': trigger_percent
            })
""",
    """            base.update({
                'poll_interval': config.get('poll_interval', 900),
                'trigger_percentage': trigger_percent,
                'season_trigger_percentage': (
                    float(os.environ['SEASON_PREFETCH_PERCENTAGE'])
                    if os.getenv('SEASON_PREFETCH_PERCENTAGE')
                    else config.get('season_trigger_percentage')
                ),
            })
""",
)

replace_once(
    "settings_db.py",
    """            base_config.update({
                'poll_interval': int(os.getenv('JELLYFIN_POLL_INTERVAL', '900')),
                'trigger_percentage': float(os.getenv('JELLYFIN_TRIGGER_PERCENTAGE', os.getenv('JELLYFIN_TRIGGER_PERCENT', '50.0')))
            })
""",
    """            base_config.update({
                'poll_interval': int(os.getenv('JELLYFIN_POLL_INTERVAL', '900')),
                'trigger_percentage': float(os.getenv('JELLYFIN_TRIGGER_PERCENTAGE', os.getenv('JELLYFIN_TRIGGER_PERCENT', '50.0'))),
                'season_trigger_percentage': (
                    float(os.environ['SEASON_PREFETCH_PERCENTAGE'])
                    if os.getenv('SEASON_PREFETCH_PERCENTAGE')
                    else None
                ),
            })
""",
)

replace_once(
    "media_processor.py",
    """def fetch_next_episodes_dropdown(series_id, season_number, episode_number, get_type, get_count):
""",
    """def fetch_next_episodes_dropdown(series_id, season_number, episode_number, get_type, get_count,
                                 playback_progress=None, season_prefetch_percentage=None):
""",
)

replace_once(
    "media_processor.py",
    """        elif get_type == 'seasons':
            # Get X full seasons starting from remaining current season
            current_season_episodes = get_episode_details(series_id, season_number)
            remaining_current = [ep['id'] for ep in current_season_episodes if ep['episodeNumber'] > episode_number]
            next_episode_ids.extend(remaining_current)
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
            # Get additional full seasons if needed
            seasons_to_get = get_count if get_count is not None else 1
            if not remaining_current:
                # Current season finished, get next X seasons
                for season_offset in range(1, seasons_to_get + 1):
                    season_episodes = get_episode_details(series_id, season_number + season_offset)
                    next_episode_ids.extend([ep['id'] for ep in season_episodes])
            elif seasons_to_get > 1:
                # Get additional seasons beyond current
                for season_offset in range(1, seasons_to_get):
                    season_episodes = get_episode_details(series_id, season_number + season_offset)
                    next_episode_ids.extend([ep['id'] for ep in season_episodes])
\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20
            logger.info(f\"Dropdown seasons mode: Found {len(next_episode_ids)} episodes across {seasons_to_get} seasons\")
            return next_episode_ids
""",
    """        elif get_type == 'seasons':
            # Keep the remainder of the current season ready, then prefetch the
            # next complete season once aggregate season progress crosses the
            # configured threshold.
            current_season_episodes = sorted(
                get_episode_details(series_id, season_number),
                key=lambda ep: ep['episodeNumber'],
            )
            remaining_current = [
                ep['id'] for ep in current_season_episodes
                if ep['episodeNumber'] > episode_number
            ]
            next_episode_ids.extend(remaining_current)

            seasons_to_get = get_count if get_count is not None else 1
            season_progress = None
            if season_prefetch_percentage is not None and playback_progress is not None:
                current_position = next(
                    (
                        position for position, ep in enumerate(current_season_episodes)
                        if ep['episodeNumber'] == episode_number
                    ),
                    None,
                )
                if current_position is not None and current_season_episodes:
                    bounded_progress = max(0.0, min(float(playback_progress), 100.0))
                    season_progress = (
                        (current_position + bounded_progress / 100.0)
                        / len(current_season_episodes)
                        * 100.0
                    )

            threshold_reached = (
                season_progress is not None
                and season_progress >= float(season_prefetch_percentage)
            )
            # Preserve upstream finale behavior when aggregate progress was not
            # supplied, and use the threshold for Jellyfin-driven automation.
            should_get_next = threshold_reached or (
                season_prefetch_percentage is None and not remaining_current
            )
            if should_get_next:
                for season_offset in range(1, seasons_to_get + 1):
                    season_episodes = get_episode_details(
                        series_id, season_number + season_offset
                    )
                    # A fully monitored season was already handed to Sonarr by
                    # an earlier event; avoid issuing the same search repeatedly.
                    if season_episodes and not all(
                        ep.get('monitored', False) for ep in season_episodes
                    ):
                        next_episode_ids.extend([ep['id'] for ep in season_episodes])
                if season_progress is not None:
                    logger.info(
                        f\"Season prefetch threshold reached: {season_progress:.1f}% \"
                        f\">= {float(season_prefetch_percentage):.1f}%\"
                    )
            elif seasons_to_get > 1:
                for season_offset in range(1, seasons_to_get):
                    season_episodes = get_episode_details(
                        series_id, season_number + season_offset
                    )
                    next_episode_ids.extend([ep['id'] for ep in season_episodes])

            logger.info(f\"Dropdown seasons mode: Found {len(next_episode_ids)} episodes across {seasons_to_get} seasons\")
            return next_episode_ids
""",
)

replace_once(
    "media_processor.py",
    """def process_episodes_for_webhook(series_id, season_number, episode_number, rule, series_title=None,
                                 prefetch_only=False):
""",
    """def process_episodes_for_webhook(series_id, season_number, episode_number, rule, series_title=None,
                                 prefetch_only=False, playback_progress=None):
""",
)

replace_once(
    "media_processor.py",
    """            next_episode_ids = fetch_next_episodes_dropdown(
                series_id, season_number, episode_number, get_type, get_count
            )
""",
    """            season_prefetch_percentage = (
                float(os.environ['SEASON_PREFETCH_PERCENTAGE'])
                if get_type == 'seasons' and os.getenv('SEASON_PREFETCH_PERCENTAGE')
                else None
            )
            next_episode_ids = fetch_next_episodes_dropdown(
                series_id,
                season_number,
                episode_number,
                get_type,
                get_count,
                playback_progress=playback_progress,
                season_prefetch_percentage=season_prefetch_percentage,
            )
""",
)

replace_once(
    "media_processor.py",
    """        prefetch_only = bool(data.get('prefetch_only', False))

        if all([series_title, season_number, episode_number]):
            return (series_title, int(season_number), int(episode_number),
                    thetvdb_id, themoviedb_id, prefetch_only)

        logger.error(f\"Required data fields not found in {filepath}\")
        return None, None, None, None, None, False

    except Exception as e:
        logger.error(f\"Failed to read or parse data from server webhook: {str(e)}\")

    return None, None, None, None, None, False
""",
    """        prefetch_only = bool(data.get('prefetch_only', False))
        playback_progress = data.get('progress_percent')

        if all([series_title, season_number, episode_number]):
            return (
                series_title,
                int(season_number),
                int(episode_number),
                thetvdb_id,
                themoviedb_id,
                prefetch_only,
                float(playback_progress) if playback_progress is not None else None,
            )

        logger.error(f\"Required data fields not found in {filepath}\")
        return None, None, None, None, None, False, None

    except Exception as e:
        logger.error(f\"Failed to read or parse data from server webhook: {str(e)}\")

    return None, None, None, None, None, False, None
""",
)

replace_once(
    "media_processor.py",
    """    series_name, season_number, episode_number, thetvdb_id, themoviedb_id, prefetch_only = get_server_activity(webhook_file)
""",
    """    (
        series_name,
        season_number,
        episode_number,
        thetvdb_id,
        themoviedb_id,
        prefetch_only,
        playback_progress,
    ) = get_server_activity(webhook_file)
""",
)

replace_once(
    "media_processor.py",
    """                process_episodes_for_webhook(series_id, season_number, episode_number, rule, series_name,
                                             prefetch_only=prefetch_only)
""",
    """                process_episodes_for_webhook(
                    series_id,
                    season_number,
                    episode_number,
                    rule,
                    series_name,
                    prefetch_only=prefetch_only,
                    playback_progress=playback_progress,
                )
""",
)

print("Applied aggregate season-progress patch")
