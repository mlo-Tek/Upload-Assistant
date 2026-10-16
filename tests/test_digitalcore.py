from src.rehostimages import _image_host
from src.trackers.digitalcore import DigitalCore


def test_uses_the_image_hosts_approved_by_digitalcore():
    assert "ptscreens" in DigitalCore.approved_image_hosts  # noqa: S101
    assert "onlyimage" not in DigitalCore.approved_image_hosts  # noqa: S101
    assert _image_host("https://img2.ptscreens.com/image.png", DigitalCore.image_host_policy.url_host_mapping) == "ptscreens"  # noqa: S101


def test_force_rehost_images_uses_digitalcore_sharex_without_changing_global_host():
    config = {
        "DEFAULT": {
            "img_host_1": "ptscreens",
            "sharex_url": "https://img.digitalcore.club/api/upload",
            "sharex_api_key": "secret",
        },
        "TRACKERS": {"DIGITALCORE": {"api_key": "tracker-key", "force_rehost_images": True}},
    }

    tracker = DigitalCore(config)

    assert tracker.image_host_policy.approved_image_hosts == ("sharex",)  # noqa: S101
    assert tracker.rehost_images_manager.default_config["img_host_1"] == "sharex"  # noqa: S101
    assert config["DEFAULT"]["img_host_1"] == "ptscreens"  # noqa: S101


def _tracker():
    config = {
        "DEFAULT": {},
        "TRACKERS": {"DIGITALCORE": {"api_key": "tracker-key", "anon": False}},
    }
    return DigitalCore(config)


def _meta(tmp_path, **attrs):
    from src.meta import Meta

    meta = Meta(path=str(tmp_path))
    for key, value in attrs.items():
        setattr(meta, key, value)
    return meta


def test_p2p_flag_is_off_for_scene_and_on_for_p2p_releases(tmp_path, monkeypatch):
    import asyncio

    tracker = _tracker()

    async def no_mediainfo(_meta):
        return ""

    async def no_description(_meta):
        return ""

    monkeypatch.setattr(tracker, "mediainfo", no_mediainfo)
    monkeypatch.setattr(tracker, "generate_description", no_description)

    scene = _meta(tmp_path, category="MOVIE", resolution="1080p", scene_name="Movie.2020.1080p.BluRay.x264-GRP")
    p2p = _meta(tmp_path, category="MOVIE", resolution="1080p", scene_name="")

    assert asyncio.run(tracker.fetch_data(scene))["p2p"] == "0"  # noqa: S101
    assert asyncio.run(tracker.fetch_data(p2p))["p2p"] == "1"  # noqa: S101


def test_firstpic_uses_first_supported_screenshot_for_movies_and_tv(tmp_path):
    import asyncio

    tracker = _tracker()
    images = [
        {"raw_url": "https://img.digitalcore.club/i/first.webp"},
        {"raw_url": "https://img.digitalcore.club/i/second.PNG?x=1"},
        {"raw_url": "https://img.digitalcore.club/i/third.jpg"},
    ]

    for category in ("MOVIE", "TV"):
        meta = _meta(tmp_path, category=category, image_list=images)
        assert asyncio.run(tracker.get_firstpic(meta)) == "https://img.digitalcore.club/i/second.PNG?x=1"  # noqa: S101


def test_firstpic_is_empty_without_usable_screenshots(tmp_path):
    import asyncio

    tracker = _tracker()

    no_images = _meta(tmp_path, category="MOVIE", image_list=[])
    only_webp = _meta(tmp_path, category="MOVIE", image_list=[{"raw_url": "https://x/y.webp"}])

    assert asyncio.run(tracker.get_firstpic(no_images)) == ""  # noqa: S101
    assert asyncio.run(tracker.get_firstpic(only_webp)) == ""  # noqa: S101


def test_firstpic_prefers_tracker_rehosted_screenshots(tmp_path):
    import asyncio

    from src.tracker_images import set_tracker_image_collection

    tracker = _tracker()
    meta = _meta(tmp_path, category="TV", image_list=[{"raw_url": "https://img.ptscreens.com/a.png"}])
    set_tracker_image_collection(meta, "DIGITALCORE", "screenshots", [{"raw_url": "https://img.digitalcore.club/i/abc.png"}])

    assert asyncio.run(tracker.get_firstpic(meta)) == "https://img.digitalcore.club/i/abc.png"  # noqa: S101
