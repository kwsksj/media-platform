"""Test Threads Posting directly."""
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from auto_post.config import ThreadsConfig
from auto_post.threads import ThreadsClient

# Configure logging
logging.basicConfig(level=logging.INFO)

def main():
    print("Testing Threads Posting...")

    # Load config directly from env vars (assuming .env is loaded or vars present)
    from dotenv import load_dotenv
    load_dotenv(override=True)

    config = ThreadsConfig.from_env()
    client = ThreadsClient(config)

    print(f"User ID from config: {config.user_id}")

    # Image to post (Use a public stable image or one from R2 if we could)
    # Let's use a sample image URL.
    # Must be public.
    # I'll use a placeholder image service.
    image_url = "https://images.unsplash.com/photo-1549880181-56a44cf4a9a5?ixlib=rb-1.2.1&auto=format&fit=crop&w=1000&q=80"
    caption = "🤖 Auto-post Test from Script (Threads Integration)"

    try:
        print(f"Posting image: {image_url}")
        print(f"Caption: {caption}")

        # 1. Create Container
        container_id = client.create_image_container(image_url, caption)
        print(f"Container created: {container_id}")

        # 2. Publish
        print("Publishing...")
        # Threads API usually requires waiting for container status to be 'FINISHED' before publish?
        # Instagram does. Let's check Threads docs or error response.
        # If it fails, I'll add status check loop.

        post_id = client.publish_container(container_id)
        print(f"SUCCESS! Post ID: {post_id}")
        print(f"Check: https://www.threads.net/t/{post_id}") # Note: ID might not be slug

    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
