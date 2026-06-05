import argparse
import datetime as dt

from oauth_hub.competitor_discovery import run_competitor_discovery


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Candidates date in YYYY-MM-DD format. Defaults to latest available candidates.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else None
    outputs = run_competitor_discovery(report_date)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Channels CSV: {outputs['channels_csv']}")
    print(f"Queries CSV: {outputs['queries_csv']}")
    print(f"Suggested competitors JSON: {outputs['suggested_json']}")
    print(f"Config example: {outputs['config_example']}")


if __name__ == "__main__":
    main()
