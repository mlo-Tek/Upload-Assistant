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


def test_release_group_does_not_treat_resolution_as_group() -> None:
    assert _release_group_from_source_title("Movie.2026-1080p") is None


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


def test_movie_scoped_history_accepts_latest_import_fallback() -> None:
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
                "data": {"importedPath": "/data/media/movies/Movie (2026)/old-name.mkv"},
            },
        ]
    }

    assert (
        _history_release_group(
            history,
            "/data/media/movies/Movie (2026)/new-name.mkv",
        )
        == "FLUX"
    )


def test_generic_history_rejects_unrelated_latest_import() -> None:
    history = {
        "records": [
            {
                "eventType": "downloadFolderImported",
                "sourceTitle": "Jurassic.Park.3.2001.2160p.UHD.BluRay-VECTOR",
                "data": {
                    "importedPath": "/data/media/movies/Jurassic Park III (2001)/Jurassic.Park.3.2001.mkv"
                },
            },
            {
                "eventType": "downloadFolderImported",
                "sourceTitle": "Jack.Reacher.2012.2160p.UHD.BluRay-VECTOR",
                "data": {"importedPath": "/data/media/movies/Jack Reacher (2012)/Jack.Reacher.2012.mkv"},
            },
        ]
    }

    assert (
        _history_release_group(
            history,
            "/data/media/movies/Waterworld (1995)/Waterworld.1995.mkv",
            allow_latest_import_fallback=False,
        )
        is None
    )


def test_generic_history_still_accepts_exact_path_match() -> None:
    history = {
        "records": [
            {
                "eventType": "downloadFolderImported",
                "sourceTitle": "Jurassic.Park.3.2001.2160p.UHD.BluRay-VECTOR",
                "data": {
                    "importedPath": "/data/media/movies/Jurassic Park III (2001)/Jurassic.Park.3.2001.mkv"
                },
            },
            {
                "eventType": "downloadFolderImported",
                "sourceTitle": "Waterworld.1995.German.DTSX.DL.2160p.UHD.UK.BluRay.DV.HDR.x265-VECTOR",
                "data": {"importedPath": "/data/media/movies/Waterworld (1995)/Waterworld.1995.mkv"},
            },
        ]
    }

    assert (
        _history_release_group(
            history,
            "/data/media/movies/Waterworld (1995)/Waterworld.1995.mkv",
            allow_latest_import_fallback=False,
        )
        == "VECTOR"
    )
