# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
from pathlib import Path
from typing import Any

import cli_ui
import langcodes

from src.console import logger
from src.meta import Meta
from src.radarr import RadarrManager
from src.trackers.common import Common
from src.trackers.UNIT3D import UNIT3D


class Luminarr(UNIT3D):
    """
    Luminarr is a Private Torrent Tracker for MOVIES / TV
    """

    tracker = "LUMINARR"
    display_name = "Luminarr"
    allows_bloated_audio = True
    base_url = "https://luminarr.me"
    banned_groups: tuple[str, ...] = ()
    id_url = f"{base_url}/api/torrents/"
    upload_url = f"{base_url}/api/torrents/upload"
    requests_url = f"{base_url}/api/requests/filter"
    search_url = f"{base_url}/api/torrents/filter"
    torrent_url = f"{base_url}/torrents/"
    supported_categories = ("TV", "MOVIE")
    tracker_urls = ("https://luminarr.me",)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config, tracker_name="LUMINARR")
        self.config = config
        self.common = Common(config)
        self.radarr_manager = RadarrManager(config)

    @staticmethod
    def _language_code(value: str | None) -> str:
        """Normalize either a language tag/code or a natural-language name."""
        if not value:
            return ""

        normalized = value.strip().replace("_", "-")

        # Metadata commonly contains BCP-47 / ISO codes such as ``en`` or
        # ``de-DE``. Parse those as tags first; langcodes.find() is intended
        # for natural-language names and must not be our first choice here.
        try:
            language = langcodes.Language.get(normalized)
            if language.is_valid() and language.language:
                return str(language.language).lower()
        except Exception:
            pass

        try:
            language = langcodes.find(normalized)
            if language.language:
                return str(language.language).lower()
        except Exception:
            pass

        return normalized.lower().split("-")[0]

    @classmethod
    def _language_display_name(cls, value: str) -> str:
        code = cls._language_code(value)
        if code:
            try:
                name = langcodes.Language.get(code).language_name()
                if name:
                    return str(name)
            except Exception:
                pass
        return value.strip().title()

    def _luminarr_dub_label(self, meta: Meta) -> str:
        """Return Luminarr's tracker-specific Dub title element for non-disc releases.

        Luminarr reserves ``Dual-Audio`` for non-English original content that
        includes an English dub. For English-original content with additional
        dubbed languages the tracker uses ``{Language} Multi`` instead.
        """
        if meta.is_disc:
            return ""

        original_code = self._language_code(meta.original_language)
        if original_code != "en":
            return ""

        audio_languages = [str(language) for language in (meta.audio_languages or []) if str(language).strip()]
        for language in audio_languages:
            language_code = self._language_code(language)
            if language_code and language_code not in {"en", "zxx", "xx"}:
                return f"{self._language_display_name(language)} Multi"

        return ""

    @staticmethod
    def _vector_prefix_group(meta: Meta) -> str:
        """Recognize VECTOR's old lowercase prefix naming convention."""
        candidates: list[Any] = [meta.video, meta.basename_no_ext]
        candidates.extend(meta.filelist or [])

        for candidate in candidates:
            if not candidate:
                continue
            basename = Path(str(candidate)).name
            if basename.casefold().startswith("vector-"):
                return "VECTOR"

        return ""

    def _radarr_is_configured(self) -> bool:
        default_config = self.config.get("DEFAULT", {})
        return any(
            str(value or "").strip()
            for key, value in default_config.items()
            if str(key).startswith("radarr_api_key")
        )

    async def _luminarr_release_group(self, meta: Meta) -> str:
        """Resolve a missing release group without requiring ``-g``.

        Normal UA filename parsing remains authoritative. VECTOR's legacy
        ``vector-...`` prefix is recognized locally. For movie filenames that
        intentionally contain no group marker, Radarr's ``movieFile.releaseGroup``
        is used as provenance when Radarr is configured.
        """
        if meta.no_tag:
            return ""

        if meta.tag:
            return str(meta.tag).strip().lstrip("-")

        prefix_group = self._vector_prefix_group(meta)
        if prefix_group:
            logger.info(f"{self.tracker}: detected release group '{prefix_group}' from original filename prefix")
            return prefix_group

        if meta.category != "MOVIE" or not meta.tmdb_id or not self._radarr_is_configured():
            return ""

        try:
            tmdb_id = int(meta.tmdb_id)
        except (TypeError, ValueError):
            return ""

        radarr_data = await self.radarr_manager.get_radarr_data(tmdb_id=tmdb_id)
        if not radarr_data:
            return ""

        release_group = str(radarr_data.get("release_group") or "").strip().lstrip("-")
        if release_group:
            logger.info(f"{self.tracker}: resolved release group '{release_group}' from Radarr")
        return release_group

    async def get_name(self, meta: Meta) -> dict[str, str]:
        name = meta.name
        dub_label = self._luminarr_dub_label(meta)

        if dub_label and "Dual-Audio" in name:
            name = name.replace("Dual-Audio", dub_label, 1)
            logger.info(f"{self.tracker}: adjusted multi-audio naming to '{dub_label}'")

        release_group = await self._luminarr_release_group(meta)
        if release_group and not name.casefold().endswith(f"-{release_group}".casefold()):
            name = f"{name.rstrip()}-{release_group}"
            logger.info(f"{self.tracker}: added automatically resolved release group '-{release_group}'")

        return {"name": name}

    async def get_additional_data(self, meta: Meta) -> dict[str, Any]:
        return {
            "mod_queue_opt_in": await self.get_flag(meta, "modq"),
        }

    async def get_additional_checks(self, meta: Meta) -> bool:
        if meta.is_disc not in ["BDMV", "DVD"] and not await self.common.check_language_requirements(
            meta, self.tracker, languages_to_check=["english"], check_audio=True, check_subtitle=True, original_language=True
        ):
            return False

        if meta.is_disc not in ["BDMV", "DVD"] and meta.resolution not in ["8640p", "4320p", "2160p", "1440p", "1080p", "1080i", "720p"]:
            if not meta.unattended or (meta.unattended and meta.unattended_confirm):
                logger.info(f"{self.tracker}: [bold red]only allows SD releases when the content does not have a higher resolution release.[/bold red]")
                if cli_ui.ask_yes_no("Do you want to upload anyway?", default=False):
                    pass
                else:
                    return False
            else:
                return False

        if not meta.is_disc and meta.container != "mkv":
            logger.info(f"{self.tracker}: [bold red]only allows MKV containers for non-disc uploads.[/bold red]")
            return False

        if not meta.valid_mi_settings:
            logger.info(f"{self.tracker}: [bold red]No encoding settings in mediainfo, skipping {self.tracker} upload.[/bold red]")
            return False

        return self.common.check_and_confirm_adult_media_upload(meta, self.tracker)
