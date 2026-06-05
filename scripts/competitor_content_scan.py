import argparse
import datetime as dt

from oauth_hub.competitor_content_scan import run_competitor_content_scan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Candidates date in YYYY-MM-DD format. Defaults to latest available candidates.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else None
    outputs = run_competitor_content_scan(report_date)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Matches CSV: {outputs['matches_csv']}")
    print(f"Topic gaps CSV: {outputs['gaps_csv']}")


if __name__ == "__main__":
    main()
