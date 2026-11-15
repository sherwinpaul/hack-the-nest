import json

from guardian.trace import parse_exa_sources

SAMPLE = (
    "Title: Chicago O'Hare thunderstorms leave ground stops\n"
    "URL: https://travelnewsradar.com/news/chicago-ohare-storm/\n"
    "Published: 2026-08-12T11:27:31.000Z\n"
    "Author: Kevin Gagnon\nHighlights:\nSee more...\n\n---\n\n"
    "Title: United travel waiver\n"
    "URL: https://www.united.com/en/us/travel-notices\n"
    "Highlights:\n...\n---\n"
    "Title: Duplicate\nURL: https://travelnewsradar.com/news/chicago-ohare-storm/\n"
)


def test_parses_title_url_domain_and_date():
    items = parse_exa_sources(SAMPLE)
    assert [i["domain"] for i in items] == ["travelnewsradar.com", "united.com"]
    assert items[0]["published"] == "2026-08-12"
    assert items[1]["published"] == ""
    assert items[0]["title"].startswith("Chicago O'Hare")


def test_parses_json_encoded_result():
    items = parse_exa_sources(json.dumps({"type": "text", "text": SAMPLE}))
    assert len(items) == 2 and items[1]["url"] == "https://www.united.com/en/us/travel-notices"


def test_no_results():
    assert parse_exa_sources("No results found") == []
