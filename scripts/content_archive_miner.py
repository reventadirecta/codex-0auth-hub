import argparse
import datetime as dt

from oauth_hub.content_archive_miner import run_archive_inventory_reconciliation, run_content_archive_miner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Archive date in YYYY-MM-DD format. Defaults to latest available diagnosis.")
    parser.add_argument(
        "--reconcile-inventory",
        "--full-inventory",
        dest="reconcile_inventory",
        action="store_true",
        help="Run the full inventory reconciliation pass against YouTube Studio and local datasets.",
    )
    parser.add_argument(
        "--studio-total",
        type=int,
        default=None,
        help="Manual Studio total used to compare against the reconciled API inventory.",
    )
    args = parser.parse_args()

    report_date = dt.date.fromisoformat(args.date) if args.date else None
    if args.reconcile_inventory:
        outputs = run_archive_inventory_reconciliation(report_date, args.studio_total)
    else:
        outputs = run_content_archive_miner(report_date)
    print(f"Report: {outputs['report']}")
    print(f"Data JSON: {outputs['json']}")
    print(f"Archive CSV: {outputs['csv']}")
    if args.reconcile_inventory:
        print(f"API Inventory CSV: {outputs['api_csv']}")
        print(f"Metadata-only CSV: {outputs['metadata_only_csv']}")
        print(f"Analytics-only CSV: {outputs['analytics_only_csv']}")
        print(f"Missing from archive miner CSV: {outputs['missing_from_v1_csv']}")
        print(f"Unavailable or deleted candidates CSV: {outputs['unavailable_csv']}")
        print(f"Studio gap summary JSON: {outputs['gap_summary_json']}")
    else:
        print(f"Public keep CSV: {outputs['public_csv']}")
        print(f"Unlisted CSV: {outputs['unlisted_csv']}")
        print(f"Private review CSV: {outputs['private_csv']}")
        print(f"Recycle CSV: {outputs['recycle_csv']}")


if __name__ == "__main__":
    main()
