
import os
import sys
from pprint import pprint

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from auto_post.config import Config
from notion_client import Client

def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()

        config = Config.load()
        client = Client(auth=config.notion.token)

        db_info = client.databases.retrieve(config.notion.database_id)
        print("Current Database Parent Info:")
        pprint(db_info.get("parent"))

        print("\nCan I create a database there?")
        if db_info["parent"]["type"] == "page_id":
            parent_id = db_info["parent"]["page_id"]
            print(f"Yes, parent is a page: {parent_id}")

            # Try to read that page to confirm access
            try:
                page = client.pages.retrieve(parent_id)
                print(f"Verified access to parent page: {page.get('url')}")
            except Exception as e:
                print(f"Warning: Could not read parent page. Might need to share it with the integration.\nError: {e}")
        else:
            print(f"Parent type is {db_info['parent']['type']}. Might be workspace or block. Creation might be tricky.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
