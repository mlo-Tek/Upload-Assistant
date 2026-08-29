# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx

from src.console import logger

MovieInfo = dict[str, Any]

_KNOWN_RELEASE_GROUPS = {"vector": "VECTOR"}
_MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".wmv"}


def _normalize_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normpath(text).casefold()


def _release_group_from_source_title(source_title: object) -> str | None:
    """Extract a release group from a Radarr history sourceTitle."""
    title = str(source_title or "").strip()
    if not title:
        return None

    basename = Path(title).name
    suffix = Path(basename).suffix.lower()
    if suffix in _MEDIA_EXTENSIONS:
        basename = basename[: -len(suffix)]

    # Standard scene/P2P release naming: ...-GROUP
    match = re.search(r"-([A-Za-z0-9][A-Za-z0-9._]{0,31})$", basename)
    if match:
        group = match.group(1).strip()
        if group:
            return _KNOWN_RELEASE_GROUPS.get(group.casefold(), group)

    # A few historical releases use a group prefix instead of a suffix.
    prefix, separator, _rest = basename.partition("-")
    if separator:
        known = _KNOWN_RELEASE_GROUPS.get(prefix.casefold())
        if known:
            return known

    return None


def _history_release_group(records: object, current_path: str | None = None) -> str | None:
    """Resolve the group from the import record matching the current movie file."""
    if isinstance(records, Mapping):
        raw_records = records.get("records", [])
    else:
        raw_records = records

    if not isinstance(raw_records, list):
        return None

    current_norm = _normalize_path(current_path)
    exact_matches: list[Mapping[str, Any]] = []
    import_records: list[Mapping[str, Any]] = []

    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            continue
        record = cast(Mapping[str, Any], raw_record)
        if str(record.get("eventType") or "").casefold() != "downloadfolderimported":
            continue

        import_records.append(record)
        data = record.get("data", {})
        if isinstance(data, Mapping) and current_norm:
            imported_path = _normalize_path(data.get("importedPath"))
            if imported_path and imported_path == current_norm:
                exact_matches.append(record)

    # Prefer provenance tied to the exact file; otherwise the newest import
    # record is the best available fallback for an upgraded movie.
    for record in [*exact_matches, *import_records]:
        group = _release_group_from_source_title(record.get("sourceTitle"))
        if group:
            return group

    return None


class RadarrManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.default_config = cast(dict[str, Any], config.get("DEFAULT", {}))

    async def _get_history_release_group(
        self,
        base_url: str,
        api_key: str,
        movie_id: int,
        current_path: str | None,
    ) -> str | None:
        headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
        urls = (
            f"{base_url}/api/v3/history/movie?movieId={movie_id}",
            f"{base_url}/api/v3/history?movieId={movie_id}&page=1&pageSize=100&sortKey=date&sortDirection=descending&includeMovie=false",
        )

        async with httpx.AsyncClient() as client:
            for url in urls:
                try:
                    response = await client.get(url, headers=headers, timeout=10.0)
                except (httpx.TimeoutException, httpx.RequestError):
                    continue

                if response.status_code != 200:
                    continue

                try:
                    history = response.json()
                except Exception:
                    continue

                release_group = _history_release_group(history, current_path)
                if release_group:
                    logger.info(f"[green]Resolved release group '-{release_group}' from Radarr history[/green]")
                    return release_group

        return None

    async def get_radarr_data(self, tmdb_id: int | None = None, filename: str | None = None) -> MovieInfo | None:
        if not any(key.startswith("radarr_api_key") for key in self.default_config):
            logger.info("[red]No Radarr API keys are configured.[/red]")
            return None

        # Try each Radarr instance until we get valid data
        instance_index = 0
        max_instances = 4  # Limit instances to prevent infinite loops

        while instance_index < max_instances:
            # Determine the suffix for this instance
            suffix = "" if instance_index == 0 else f"_{instance_index}"
            api_key_name = f"radarr_api_key{suffix}"
            url_name = f"radarr_url{suffix}"

            # Check if this instance exists in config
            api_key_value = self.default_config.get(api_key_name)
            if not isinstance(api_key_value, str) or not api_key_value.strip():
                # This slot isn't configured; try the next suffix (supports configs starting at _1)
                instance_index += 1
                continue

            # Get instance-specific configuration
            base_url_value = self.default_config.get(url_name)
            if not isinstance(base_url_value, str) or not base_url_value.strip():
                instance_index += 1
                continue

            api_key = api_key_value.strip()
            base_url = base_url_value.strip().rstrip("/")

            logger.debug(f"[blue]Trying Radarr instance {instance_index if instance_index > 0 else 'default'}[/blue]")

            # Build the appropriate URL
            if tmdb_id:
                url = f"{base_url}/api/v3/movie?tmdbId={tmdb_id}&excludeLocalCovers=true"
            elif filename:
                url = f"{base_url}/api/v3/movie/lookup?term={filename}"
            else:
                instance_index += 1
                continue

            headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

            logger.debug(f"[green]TMDB ID {tmdb_id}[/green]")
            logger.debug(f"[blue]Radarr URL:[/blue] {url}")

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=headers, timeout=10.0)

                if response.status_code == 200:
                    data = response.json()

                    logger.debug(f"[blue]Radarr Response Status:[/blue] {response.status_code}")
                    logger.debug(f"[blue]Radarr Response Data:[/blue] {data}")

                    # Check if we got valid data by trying to extract movie info
                    movie_data = await self.extract_movie_data(data, filename)

                    if movie_data and (movie_data.get("imdb_id") or movie_data.get("tmdb_id")):
                        if not movie_data.get("release_group"):
                            movie_id = movie_data.get("radarr_id")
                            current_path = movie_data.get("movie_file_path")
                            if isinstance(movie_id, int) and movie_id > 0:
                                history_group = await self._get_history_release_group(base_url, api_key, movie_id, str(current_path or ""))
                                if history_group:
                                    movie_data["release_group"] = history_group

                        logger.info(f"[green]Found valid movie data from Radarr instance {instance_index if instance_index > 0 else 'default'}[/green]")
                        return movie_data
                else:
                    logger.info(
                        f"[yellow]Failed to fetch from Radarr instance {instance_index if instance_index > 0 else 'default'}: {response.status_code} - {response.text}[/yellow]"
                    )

            except httpx.TimeoutException:
                logger.info(f"[red]Timeout when fetching from Radarr instance {instance_index if instance_index > 0 else 'default'}[/red]")
            except httpx.RequestError as e:
                logger.error(f"[red]Error fetching from Radarr instance {instance_index if instance_index > 0 else 'default'}: {e}[/red]")
            except Exception as e:
                logger.error(f"[red]Unexpected error with Radarr instance {instance_index if instance_index > 0 else 'default'}: {e}[/red]")

            # Move to the next instance
            instance_index += 1

        # If we got here, no instances provided valid data
        logger.info("[yellow]No Radarr instance returned valid movie data.[/yellow]")
        return None

    async def extract_movie_data(self, radarr_data: Any, filename: str | None = None) -> MovieInfo | None:
        if not radarr_data or not isinstance(radarr_data, list):
            return {"imdb_id": None, "tmdb_id": None, "year": None, "genres": [], "release_group": None}
        items = cast(list[Mapping[str, Any]], radarr_data)
        if len(items) == 0:
            return {"imdb_id": None, "tmdb_id": None, "year": None, "genres": [], "release_group": None}

        if filename:
            movie: Mapping[str, Any] | None = None
            for item in items:
                movie_file = cast(Mapping[str, Any], item.get("movieFile", {}))
                if movie_file.get("originalFilePath") == filename:
                    movie = item
                    break
            else:
                return None
        else:
            movie = items[0]

        release_group = None
        movie_file = cast(Mapping[str, Any], movie.get("movieFile", {}))
        if movie_file.get("releaseGroup"):
            release_group = movie_file["releaseGroup"]

        return {
            "imdb_id": int(str(movie.get("imdbId", "tt0")).replace("tt", "")) if movie.get("imdbId") else None,
            "tmdb_id": movie.get("tmdbId", None),
            "year": movie.get("year", None),
            "genres": movie.get("genres", []),
            "release_group": release_group if release_group else None,
            "radarr_id": movie.get("id") if isinstance(movie.get("id"), int) else None,
            "movie_file_path": movie_file.get("path") if movie_file.get("path") else None,
        }
