"""Command-line interface."""

import logging
import sys
from datetime import datetime
from pathlib import Path

import click

from .config import Config
from .importer import Importer
from .poster import Poster

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@click.group()
@click.option(
    "--env-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to .env file",
)
@click.option("--debug/--no-debug", default=False, help="Enable debug logging")
@click.pass_context
def main(ctx, env_file: Path | None, debug: bool):
    """Instagram/X auto-posting system for woodcarving class photos."""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file


@main.command()
@click.option("--date", type=click.DateTime(formats=["%Y-%m-%d"]), help="Target date (default: today)")
@click.pass_context
def post(ctx, date: datetime | None):
    """Run the daily posting job."""
    config = Config.load(ctx.obj.get("env_file"))
    poster = Poster(config)

    target_date = date or datetime.now()
    stats = poster.run_daily_post(target_date)

    click.echo(f"Processed: {stats['processed']}")
    click.echo(f"Instagram success: {stats['ig_success']}")
    click.echo(f"X success: {stats['x_success']}")
    click.echo(f"Errors: {stats['errors']}")

    if stats["errors"] > 0:
        sys.exit(1)


@main.command()
@click.argument("page_id")
@click.option(
    "--platform",
    type=click.Choice(["instagram", "x", "both"]),
    default="both",
    help="Platform to post to",
)
@click.pass_context
def test_post(ctx, page_id: str, platform: str):
    """Test post a specific Notion page."""
    config = Config.load(ctx.obj.get("env_file"))
    poster = Poster(config)

    result = poster.test_post(page_id, platform)

    if "instagram_post_id" in result:
        click.echo(f"Instagram post ID: {result['instagram_post_id']}")
    if "x_post_id" in result:
        click.echo(f"X post ID: {result['x_post_id']}")


@main.command()
@click.pass_context
def refresh_token(ctx):
    """Refresh the Instagram access token."""
    config = Config.load(ctx.obj.get("env_file"))
    from .instagram import InstagramClient

    client = InstagramClient(config.instagram)
    new_token, expiry = client.refresh_token()

    click.echo(f"New token: {new_token[:20]}...")
    click.echo(f"Expiry: {expiry.strftime('%Y-%m-%d')}")
    click.echo("\nPlease update INSTAGRAM_ACCESS_TOKEN in your .env file or GitHub secrets")


@main.command()
@click.option("--student", help="Filter by student name")
@click.option("--unposted", is_flag=True, help="Show only unposted items")
@click.pass_context
def list_works(ctx, student: str | None, unposted: bool):
    """List all work items from Notion."""
    config = Config.load(ctx.obj.get("env_file"))
    poster = Poster(config)

    works = poster.list_works(student=student, only_unposted=unposted)

    click.echo(f"Found {len(works)} works:\n")
    for work in works:
        status = []
        if work.ig_posted:
            status.append("IG")
        if work.x_posted:
            status.append("X")
        status_str = f" [{','.join(status)}]" if status else ""

        click.echo(f"  {work.work_name}{status_str}")
        click.echo(f"    Page ID: {work.page_id}")
        if work.student_name:
            click.echo(f"    Student: {work.student_name}")
        if work.scheduled_date:
            click.echo(f"    Scheduled: {work.scheduled_date.strftime('%Y-%m-%d')}")
        click.echo(f"    Images: {len(work.image_urls)}")
        click.echo()


@main.command()
@click.pass_context
def check_notion(ctx):
    """Check Notion database connection and schema."""
    config = Config.load(ctx.obj.get("env_file"))
    from .notion_db import NotionDB

    notion = NotionDB(config.notion.token, config.notion.database_id)

    try:
        info = notion.get_database_info()
        click.echo(f"Database: {info['title'][0]['plain_text'] if info.get('title') else 'Untitled'}")
        click.echo(f"ID: {info['id']}")
        click.echo("\nProperties:")
        for name, prop in info.get("properties", {}).items():
            click.echo(f"  - {name} ({prop['type']})")
    except Exception as e:
        click.echo(f"Error connecting to Notion: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Import commands for photo grouping
# ============================================================================


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--threshold", "-t", default=10, help="Time gap threshold in minutes (default: 10)")
@click.option("--max-per-group", "-m", default=10, help="Max photos per group (default: 10)")
@click.pass_context
def preview_groups(ctx, folder: Path, threshold: int, max_per_group: int):
    """Preview photo grouping without importing."""
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)
    importer.preview_groups(folder, threshold, max_per_group)


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("output", type=click.Path(path_type=Path))
@click.option("--threshold", "-t", default=10, help="Time gap threshold in minutes (default: 10)")
@click.option("--max-per-group", "-m", default=10, help="Max photos per group (default: 10)")
@click.pass_context
def export_groups(ctx, folder: Path, output: Path, threshold: int, max_per_group: int):
    """Export photo grouping to JSON for manual editing."""
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)
    importer.export_preview(folder, output, threshold, max_per_group)
    click.echo(f"\nGrouping exported to: {output}")
    click.echo("Edit this file to adjust work names, groupings, or student names.")
    click.echo("Then use 'import-groups' to import from this file.")


@main.command()
@click.argument("grouping_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--student", "-s", help="Student name for all imported works")
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date for scheduling (increments by 1 day per group)",
)
@click.option("--dry-run", is_flag=True, help="Preview import without making changes")
@click.pass_context
def import_groups(ctx, grouping_file: Path, student: str | None, start_date: datetime | None, dry_run: bool):
    """Import photos using an edited grouping file."""
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)

    stats = importer.import_from_file(
        grouping_file,
        student_name=student,
        start_date=start_date,
        dry_run=dry_run,
    )

    if stats["errors"] > 0:
        sys.exit(1)


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--threshold", "-t", default=10, help="Time gap threshold in minutes (default: 10)")
@click.option("--max-per-group", "-m", default=10, help="Max photos per group (default: 10)")
@click.option("--student", "-s", help="Student name for all imported works")
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date for scheduling (increments by 1 day per group)",
)
@click.option("--dry-run", is_flag=True, help="Preview import without making changes")
@click.pass_context
def import_direct(ctx, folder: Path, threshold: int, max_per_group: int, student: str | None, start_date: datetime | None, dry_run: bool):
    """Import photos directly from folder without manual review."""
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)

    if not dry_run:
        click.confirm(
            f"This will import photos from {folder} and create Notion entries. Continue?",
            abort=True,
        )

    stats = importer.import_direct(
        folder,
        threshold_minutes=threshold,
        max_per_group=max_per_group,
        student_name=student,
        start_date=start_date,
        dry_run=dry_run,
    )

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
