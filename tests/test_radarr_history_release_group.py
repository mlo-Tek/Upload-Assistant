from src.radarr import _history_release_group, _release_group_from_source_title


def test_release_group_from_standard_source_title() -> None:
    assert (
        _release_group_from_source_title(
            "Waterworld.1995.German.DL.2160p.UHD.BluRay.DTS-HD.MA.7.1.DV.HDR.x265-VECTOR"
        )
        == "VECTOR"
    )


def test_release_group_from_known_prefix_source_title() -> None:
    assert _release_group_from_source_title("vector-hueterlicht-1080p") == "VECTOR"


def test_history_prefers_import_record_for_current_file() -> None:
    records = [
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": "Waterworld.1995.2160p.WEB-DL-GROUPA",
            "data": {"importedPath": "/data/media/movies/Waterworld (1995)/old.mkv"},
        },
        {
            "eventType": "downloadFolderImported",
            "sourceTitle": "Waterworld.1995.German.DL.2160p.UHD.BluRay.DTS-X.7.1.DV.HDR.x265-VECTOR",
            "data": {"importedPath": "/data/media/movies/Waterworld (1995)/Waterworld.1995.mkv"},
        },
    ]

    assert (
        _history_release_group(
            records,
            "/data/media/movies/Waterworld (1995)/Waterworld.1995.mkv",
        )
        == "VECTOR"
    )


def test_history_accepts_paged_response_and_latest_import_fallback() -> None:
    history = {
        "records": [
            {
                "eventType": "grabbed",
                "sourceTitle": "Ignored.Release-GROUPX",
                "data": {},
            },
            {
                "eventType": "downloadFolderImported",
                "sourceTitle": "Movie.2026.1080p.WEB-DL-FLUX",
                "data": {},
            },
        ]
    }

    assert _history_release_group(history) == "FLUX"
