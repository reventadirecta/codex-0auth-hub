import argparse
import datetime as dt

from oauth_hub.opportunities import run_channel_opportunities


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Diagnosis date in YYYY-MM-DD format. Defaults to latest available diagnosis.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else None
    outputs = run_channel_opportunities(report_date)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Data CSV: {outputs['csv']}")


if __name__ == "__main__":
    main()
