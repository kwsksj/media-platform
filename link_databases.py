
import os
import sys
import logging

sys.path.append(os.path.join(os.getcwd(), "src"))
from auto_post.config import Config
from notion_client import Client

logging.basicConfig(level=logging.INFO)

def main():
    config = Config.load()
    client = Client(auth=config.notion.token, notion_version="2022-06-28")

    works_db_id = config.notion.database_id
    keywords_db_id = "2ee57846-aac2-805d-ab57-000b306d14d6" # Derived from search

    print(f"Linking Works DB ({works_db_id}) to Keywords DB ({keywords_db_id})...")

    try:
        # Update Works DB to add 'TagsRelation'
        client.databases.update(
            database_id=works_db_id,
            properties={
                "タグ(新)": {
                    "relation": {
                        "database_id": keywords_db_id,
                        # "type": "dual_property", # Start with simple one way or separate
                        # For simple tagging, single_property (one-way) is easier if we don't need backlink
                        # BUT user wants to see list of works on Tag page -> Dual Property needed!
                        "dual_property": {},
                        # "synced_property_name" seems required for dual?
                    }
                }
            }
        )
        print("Success! Added 'タグ(新)' relation property.")

    except Exception as e:
        print(f"Error: {e}")
        # Sometimes adding dual property requires specifying correct args or using separate update calls

if __name__ == "__main__":
    main()
