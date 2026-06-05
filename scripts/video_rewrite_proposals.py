import argparse
import datetime as dt

from oauth_hub.rewrite_proposals import run_video_rewrite_proposals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Candidates date in YYYY-MM-DD format. Defaults to latest available candidates.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else None
    outputs = run_video_rewrite_proposals(report_date)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Title Bank CSV: {outputs['title_bank_csv']}")
    print(f"Thumbnail Ideas CSV: {outputs['thumbnail_csv']}")
    print(f"Orchestrator Decisions CSV: {outputs['orchestrator_csv']}")


if __name__ == "__main__":
    main()
