import argparse

from googleapiclient.discovery import build

from oauth_hub.google_auth import get_credentials
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    config, _account, service, entry = get_connection("blogger", args.connection_id)
    token_id = entry.get("tokenId", entry["id"])
    creds = get_credentials(config, f"{service}.{token_id}", entry.get("scopes", []))
    blogger = build("blogger", "v3", credentials=creds)

    blog_id = entry.get("blogId")
    if blog_id:
        blog = blogger.blogs().get(blogId=blog_id).execute()
        print(f"{blog.get('id')} | {blog.get('name')} | {blog.get('url')}")
    else:
        response = blogger.blogs().listByUser(userId="self").execute()
        for blog in response.get("items", []):
            print(f"{blog.get('id')} | {blog.get('name')} | {blog.get('url')}")


if __name__ == "__main__":
    main()
