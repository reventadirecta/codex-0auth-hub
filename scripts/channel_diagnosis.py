import argparse
import datetime as dt

from oauth_hub.diagnosis import run_channel_diagnosis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format. Defaults to today.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    outputs = run_channel_diagnosis(report_date)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Data CSV 30d: {outputs['csv_30']}")
    print(f"Data CSV 90d: {outputs['csv_90']}")


if __name__ == "__main__":
    main()
