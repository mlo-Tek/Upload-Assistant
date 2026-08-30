# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import re
from typing import Any

import cli_ui
import langcodes

from src.console import logger
from src.meta import Meta
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

    @staticmethod
    def _language_code(value: str | None) -> str:
        """Normalize either a language tag/code or a natural-language name."""
        if not value:
            return ""

        normalized = value.strip().replace("_", "-")
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

    @classmethod
    def _audio_languages(cls, meta: Meta) -> list[tuple[str, str]]:
        """Return unique audio languages as ``(code, display-name)`` pairs."""
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        values = meta.audio_languages if isinstance(meta.audio_languages, list) else [meta.audio_languages] if meta.audio_languages else []
        for raw in values:
            text = str(raw or "").strip()
            code = cls._language_code(text)
            if not code or code in {"zxx", "xx", "und"} or code in seen:
                continue
            seen.add(code)
            result.append((code, cls._language_display_name(text)))
        return result

    def _luminarr_dub_label(self, meta: Meta) -> str:
        """Return Luminarr's tracker-specific Dub title element.

        Luminarr reserves ``Dual-Audio`` for a non-English original that carries
        both original audio and English. English-original content with exactly
        one additional language uses ``{Language} Multi``. With multiple extra
        languages, use ``Multi`` rather than inventing one language label.
        """
        if meta.is_disc:
            return ""

        original = self._language_code(meta.original_language)
        tracks = self._audio_languages(meta)
        codes = {code for code, _ in tracks}
        if not codes or len(codes) == 1 and original in codes:
            return ""

        if original == "en":
            extras = [(code, name) for code, name in tracks if code != "en"]
            if len(extras) == 1:
                return f"{extras[0][1]} Multi"
            if len(extras) >= 2:
                return "Multi"
            return ""

        if original:
            if codes == {"en"}:
                return "Dubbed"
            if original in codes and "en" in codes:
                return "Dual-Audio" if len(codes) == 2 else "Multi"
            if original in codes and len(codes) == 2:
                other = next(((code, name) for code, name in tracks if code != original), None)
                return f"{other[1]} Multi" if other else ""
            if len(codes) >= 3:
                return "Multi"

        return ""

    @staticmethod
    def _replace_dub_token(name: str, label: str) -> str:
        """Replace UA's generic language element without touching codec/source tokens."""
        clean = " ".join(str(name or "").split())
        if not label:
            return clean
        pattern = r"\b(?:Dual-Audio|Dubbed|MULTi|Multi|[A-Za-z][A-Za-z -]*?\s+(?:MULTi|Multi|Dubbed))\b"
        if re.search(pattern, clean):
            return re.sub(pattern, label, clean, count=1)
        return clean

    @classmethod
    def _insert_dub_label(cls, name: str, meta: Meta, label: str) -> str:
        clean = cls._replace_dub_token(name, label)
        if not label or label in clean:
            return clean

        # If UA did not emit a language element, place it immediately before
        # the audio codec. This keeps Luminarr's tracker-facing order stable.
        audio = str(meta.audio or "").strip()
        if audio and audio in clean:
            return clean.replace(audio, f"{label} {audio}", 1)
        return clean

    async def get_name(self, meta: Meta) -> dict[str, str]:
        name = " ".join(str(meta.name or "").split())
        dub_label = self._luminarr_dub_label(meta)
        adjusted = self._insert_dub_label(name, meta, dub_label)
        if adjusted != name:
            logger.info(f"{self.tracker}: adjusted multi-audio naming to '{dub_label}'")
        return {"name": adjusted}

    async def get_additional_data(self, meta: Meta) -> dict[str, Any]:
        return {
            "mod_queue_opt_in": await self.get_flag(meta, "modq"),
        }

    async def get_additional_checks(self, meta: Meta) -> bool:
        if meta.is_disc not in ["BDMV", "DVD"]:
            tracks = self._audio_languages(meta)
            if len(tracks) > 1 and not self._language_code(meta.original_language):
                logger.info(
                    f"{self.tracker}: [bold red]cannot safely determine tracker-specific multi-audio naming without the original language. Skipping upload.[/bold red]"
                )
                return False

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
