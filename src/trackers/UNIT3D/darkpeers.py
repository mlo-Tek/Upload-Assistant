# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
"""DarkPeers safety overrides for original-release-name enforcement.

DarkPeers rule 4.12 forbids re-tags. For Radarr-backed movies that have since
been renamed, recover the original imported sourceTitle so the original release
group can be retained. The tracker-facing title itself is rebuilt from Upload
Assistant metadata because DarkPeers requires its own naming-guide format rather
than Scene dot naming.
"""

import os
import re
from collections.abc import Mapping
from typing import Any, cast

import httpx

from src.console import logger
from src.meta import Meta
from src.trackers.UNIT3D.darkpeers_base import DarkPeers as _DarkPeersBase


class DarkPeers(_DarkPeersBase):
    """DarkPeers adapter with fail-safe provenance and tracker naming."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._original_movie_name_cache: dict[str, str] = {}

    @staticmethod
    def _normalize_path(value: object) -> str:
        text = str(value or "").strip()
        return os.path.normpath(text).casefold() if text else ""

    @staticmethod
    def _source_title_matches_group(source_title: str, expected_group: str | None) -> bool:
        """Check whether a Radarr sourceTitle carries the expected release group."""
        group = str(expected_group or "").lstrip("-").strip().casefold()
        if not group:
            return True

        # sourceTitle normally has no extension. Do not use os.path.splitext()
        # here because dots are part of release names (for example
        # ``...HDR.x265-VECTOR``) and splitext would incorrectly treat
        # ``.x265-VECTOR`` as a file extension, removing the release group.
        title = str(source_title or "").strip().casefold()
        for extension in (".mkv", ".mp4", ".m2ts", ".avi", ".ts", ".mov", ".wmv"):
            if title.endswith(extension):
                title = title[: -len(extension)]
                break

        return title.endswith(f"-{group}") or title.startswith(f"{group}-")

    @staticmethod
    def _release_group(source_title: str) -> str:
        """Extract a conservative final release-group token from a sourceTitle."""
        title = str(source_title or "").strip()
        for extension in (".mkv", ".mp4", ".m2ts", ".avi", ".ts", ".mov", ".wmv"):
            if title.casefold().endswith(extension):
                title = title[: -len(extension)]
                break
        match = re.search(r"-([A-Za-z0-9][A-Za-z0-9._-]{0,63})$", title)
        return match.group(1) if match else ""

    @staticmethod
    def _replace_release_group(name: str, group: str) -> str:
        """Ensure a generated DarkPeers name keeps the recovered original group."""
        clean = " ".join(str(name or "").split())
        group = str(group or "").lstrip("-").strip()
        if not clean or not group:
            return clean
        if re.search(r"-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", clean):
            return re.sub(r"-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", f"-{group}", clean)
        return f"{clean}-{group}"

    @classmethod
    def _darkpeers_audio_tag(cls, meta: Meta) -> str:
        """Return the DUB element from the DarkPeers naming decision matrix."""
        if meta.is_disc:
            return "SKIPPED"

        audio = cls._languages(meta.audio_languages)
        original = cls._normalise_language(meta.original_language)
        if not audio or (len(audio) == 1 and original in audio):
            return "SKIPPED"

        # English originals use Language MULTi for English + exactly one other
        # language, and MULTi for English + two or more additional languages.
        if original == "english":
            if "english" in audio:
                other = audio - {"english"}
                if len(other) == 1:
                    return f"{next(iter(other)).title()} MULTi"
                if len(other) >= 2:
                    return "MULTi"
            if len(audio) == 1:
                return f"{next(iter(audio)).title()} Dubbed"
            return "MULTi" if len(audio) >= 3 else "SKIPPED"

        # Non-English originals: English-only is Dubbed; original + English is
        # Dual-Audio; three or more included languages are MULTi.
        if audio == {"english"} and original:
            return "Dubbed"
        if original and original in audio:
            if "english" in audio and len(audio) == 2:
                return "Dual-Audio"
            if len(audio) >= 3:
                return "MULTi"
            other = audio - {original}
            if len(other) == 1:
                return f"{next(iter(other)).title()} MULTi"
            return "SKIPPED"

        # English plus exactly one other language remains Language MULTi even
        # when the original language itself is absent.
        if "english" in audio:
            other = audio - {"english"}
            if len(other) == 1:
                return f"{next(iter(other)).title()} MULTi"
            return "MULTi"

        # Nordic-only dubbing is explicitly represented as Language Dubbed.
        if len(audio) == 1:
            only = next(iter(audio))
            if original and only != original and only in cls._NORDIC_LANGUAGES:
                return f"{only.title()} Dubbed"
            return "SKIPPED"

        # Otherwise avoid inventing a label for an ambiguous combination.
        return "SKIPPED"

    @classmethod
    def _apply_audio_tag(cls, name: str, meta: Meta, audio_tag: str) -> str:
        """Replace UA's generic dub token with the DarkPeers DUB element."""
        clean = " ".join(str(name or "").split())
        if not clean or not audio_tag or audio_tag == "SKIPPED":
            return clean

        # UA commonly emits Dual-Audio for two-language releases. Replace the
        # generic token rather than appending a duplicate DUB element.
        token_pattern = r"\b(?:Dual-Audio|Dubbed|MULTi|[A-Za-z]+ MULTi|[A-Za-z]+ Dubbed)\b"
        if re.search(token_pattern, clean):
            return re.sub(token_pattern, audio_tag, clean, count=1)

        # If no generic token is present, insert the DUB element before the
        # audio codec where possible. This keeps DP's SOURCE/TYPE -> DUB ->
        # ACodec/Channels order without rebuilding the entire title.
        audio_text = str(meta.audio or "").strip()
        if audio_text and audio_text in clean:
            return clean.replace(audio_text, f"{audio_tag} {audio_text}", 1)
        return clean

    @classmethod
    def _normalize_dp_name(cls, name: str, meta: Meta, audio_tag: str) -> str:
        """Apply tracker-specific spelling and ordering cleanups."""
        clean = " ".join(str(name or "").replace(".", " ").split()) if "." in str(name or "") and " " not in str(name or "") else " ".join(str(name or "").split())
        clean = re.sub(r"\bDTSX\b", "DTS:X", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\bDL\b", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        clean = cls._apply_audio_tag(clean, meta, audio_tag)
        return " ".join(clean.split())

    @classmethod
    def _history_source_title(
        cls,
        records: object,
        current_path: str | None = None,
        *,
        allow_latest_import_fallback: bool = True,
        expected_group: str | None = None,
    ) -> str | None:
        """Return a trustworthy Radarr import sourceTitle.

        Exact imported-path matches are preferred. When Upload-Assistant adds a
        newly-created torrent back to qBittorrent, Radarr can later record a
        newer, stripped sourceTitle such as ``Waterworld.1995`` for the same
        imported path. If a release group is known, only history entries carrying
        that group are eligible so the stripped entry cannot shadow the original
        release name required by DarkPeers rule 4.12.

        Falling back to the newest import is permitted only for Radarr's
        movie-scoped history endpoint; some Radarr versions ignore movieId on the
        generic history endpoint.
        """
        raw_records: object
        if isinstance(records, Mapping):
            raw_records = records.get("records", [])
        else:
            raw_records = records
        if not isinstance(raw_records, list):
            return None

        current_norm = cls._normalize_path(current_path)
        exact_titles: list[str] = []
        import_titles: list[str] = []

        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                continue
            record = cast(Mapping[str, Any], raw_record)
            if str(record.get("eventType") or "").casefold() != "downloadfolderimported":
                continue

            source_title = str(record.get("sourceTitle") or "").strip()
            if not source_title:
                continue
            import_titles.append(source_title)

            data = record.get("data", {})
            if isinstance(data, Mapping) and current_norm:
                imported_path = cls._normalize_path(data.get("importedPath"))
                if imported_path and imported_path == current_norm:
                    exact_titles.append(source_title)

        def eligible(titles: list[str]) -> str | None:
            for title in titles:
                if cls._source_title_matches_group(title, expected_group):
                    return title
            return None

        if exact_titles:
            return eligible(exact_titles)
        if allow_latest_import_fallback and import_titles:
            return eligible(import_titles)
        return None

    def _radarr_enabled(self, meta: Meta) -> bool:
        default = self.config.get("DEFAULT", {})
        return bool(
            isinstance(default, dict)
            and default.get("use_radarr", False)
            and meta.tmdb_id
            and any(str(key).startswith("radarr_api_key") for key in default)
        )

    async def _resolve_original_movie_name(self, meta: Meta) -> str:
        """Resolve the exact release name used by Radarr when this movie imported."""
        scene_name = str(meta.scene_name or "").strip()
        if scene_name:
            return scene_name
        if str(meta.category or "").upper() != "MOVIE" or not self._radarr_enabled(meta):
            return ""

        try:
            tmdb_id = int(meta.tmdb_id or 0)
        except (TypeError, ValueError):
            return ""
        if tmdb_id <= 0:
            return ""

        expected_group = str(meta.tag or "").lstrip("-").strip()
        cache_key = f"{tmdb_id}:{expected_group.casefold()}"
        cached = self._original_movie_name_cache.get(cache_key)
        if cached:
            return cached

        default_raw = self.config.get("DEFAULT", {})
        default = cast(dict[str, Any], default_raw) if isinstance(default_raw, dict) else {}

        async with httpx.AsyncClient() as client:
            for instance_index in range(4):
                suffix = "" if instance_index == 0 else f"_{instance_index}"
                api_key = str(default.get(f"radarr_api_key{suffix}") or "").strip()
                base_url = str(default.get(f"radarr_url{suffix}") or "").strip().rstrip("/")
                if not api_key or not base_url:
                    continue

                headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
                try:
                    movie_response = await client.get(
                        f"{base_url}/api/v3/movie?tmdbId={tmdb_id}&excludeLocalCovers=true",
                        headers=headers,
                        timeout=10.0,
                    )
                except (httpx.TimeoutException, httpx.RequestError):
                    continue
                if movie_response.status_code != 200:
                    continue

                try:
                    movie_payload = movie_response.json()
                except (ValueError, TypeError):
                    continue
                if not isinstance(movie_payload, list) or not movie_payload or not isinstance(movie_payload[0], Mapping):
                    continue

                movie = cast(Mapping[str, Any], movie_payload[0])
                movie_id = movie.get("id")
                movie_file = movie.get("movieFile", {})
                current_path = str(movie_file.get("path") or "") if isinstance(movie_file, Mapping) else ""
                if not isinstance(movie_id, int) or movie_id <= 0:
                    continue

                endpoints = (
                    (f"{base_url}/api/v3/history/movie?movieId={movie_id}", True),
                    (
                        f"{base_url}/api/v3/history?movieId={movie_id}&page=1&pageSize=100&sortKey=date&sortDirection=descending&includeMovie=false",
                        False,
                    ),
                )
                for url, allow_latest in endpoints:
                    try:
                        history_response = await client.get(url, headers=headers, timeout=10.0)
                    except (httpx.TimeoutException, httpx.RequestError):
                        continue
                    if history_response.status_code != 200:
                        continue
                    try:
                        history = history_response.json()
                    except (ValueError, TypeError):
                        continue

                    source_title = self._history_source_title(
                        history,
                        current_path,
                        allow_latest_import_fallback=allow_latest,
                        expected_group=expected_group or None,
                    )
                    if source_title:
                        self._original_movie_name_cache[cache_key] = source_title
                        logger.info(f"{self.tracker}: using original Radarr release name '{source_title}' for provenance")
                        return source_title

        return ""

    async def get_audio(self, meta: Meta) -> str:
        if not meta.language_checked:
            from src.languages import languages_manager

            await languages_manager.process_desc_language(meta, tracker=self.tracker)
        return self._darkpeers_audio_tag(meta)

    async def get_additional_checks(self, meta: Meta) -> bool:
        # Rule 4.12 is explicitly bannable. If Radarr integration is enabled for
        # a non-scene movie, never proceed when import provenance cannot be
        # recovered. The sourceTitle is used to preserve the original group, not
        # as the tracker-facing title, because DP requires its naming-guide format.
        if str(meta.category or "").upper() == "MOVIE" and not str(meta.scene_name or "").strip() and self._radarr_enabled(meta):
            if not await self._resolve_original_movie_name(meta):
                logger.info(
                    f"{self.tracker}: [bold red]could not recover the original Radarr release name required by rule 4.12. Skipping upload to avoid a re-tag.[/bold red]"
                )
                return False
        return await super().get_additional_checks(meta)

    async def get_name(self, meta: Meta) -> dict[str, str]:
        original_name = ""
        if str(meta.category or "").upper() == "MOVIE":
            original_name = await self._resolve_original_movie_name(meta)

        # Always prefer UA's metadata-built name for DP. Scene/Radarr source
        # titles often use dot naming and non-DP tokens such as DL/DTSX/region.
        # Temporarily hide scene_name so the base adapter cannot select it.
        scene_name = meta.scene_name
        try:
            meta.scene_name = ""
            result = await super().get_name(meta)
        finally:
            meta.scene_name = scene_name

        name = str(result.get("name") or meta.name or "")
        audio_tag = await self.get_audio(meta)
        name = self._normalize_dp_name(name, meta, audio_tag)

        # Rule 4.12: keep the recovered original release group even when the
        # tracker-facing title is reformatted to comply with DP's naming guide.
        group = self._release_group(original_name)
        if group:
            name = self._replace_release_group(name, group)

        return {"name": name}
