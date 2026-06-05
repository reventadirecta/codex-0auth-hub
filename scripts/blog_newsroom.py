import argparse
import datetime as dt

from oauth_hub.blog_newsroom import build_artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", help="Optional topic for the newsroom flow.")
    parser.add_argument("--mode", default="draft", help="Workflow mode. Defaults to draft.")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format. Defaults to today.")
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    outputs = build_artifacts(report_date, args.topic, args.mode)
    print(f"Report: {outputs['report']}")
    print(f"JSON: {outputs['json']}")
    print(f"Article: {outputs['article']}")
    print(f"Claims: {outputs['claims']}")
    print(f"Sources: {outputs['sources']}")
    print(f"Fact check: {outputs['fact_check']}")
    print(f"Packaging: {outputs['packaging']}")
    print(f"Editorial decision: {outputs['editorial_decision']}")


if __name__ == "__main__":
    main()
