import argparse
import datetime as dt

from oauth_hub.youtube_tag_intelligence import run_youtube_tag_intelligence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--seed", help="Optional seed filter such as Ollama.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    outputs = run_youtube_tag_intelligence(report_date, args.seed)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Tag CSV: {outputs['tag_csv']}")
    print(f"Hashtag CSV: {outputs['hashtag_csv']}")
    print(f"Search Phrase CSV: {outputs['search_phrase_csv']}")
    print(f"Topic Entity CSV: {outputs['topic_entity_csv']}")
    print(f"Calibrated Global CSV: {outputs['calibrated_global_csv']}")
    print(f"Source Availability JSON: {outputs['availability_json']}")


if __name__ == "__main__":
    main()
