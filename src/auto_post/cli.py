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
@click.option("--dry-run", is_flag=True, help="Preview posting without executing")
@click.option(
    "--platform",
    type=click.Choice(["instagram", "x", "threads", "all"]),
    default="all",
    help="Platform to post to (default: all). When specified, only items unposted to that platform are selected."
)
@click.pass_context
def post(ctx, date: datetime | None, dry_run: bool, platform: str):
    """Run the daily posting job."""
    config = Config.load(ctx.obj.get("env_file"))
    poster = Poster(config)

    target_date = date or datetime.now()

    # Convert platform arg to list
    if platform == "all":
        platforms = ["instagram", "x", "threads"]
    else:
        platforms = [platform]

    stats = poster.run_daily_post(target_date, dry_run=dry_run, platforms=platforms)

    click.echo(f"Processed: {stats['processed']}")
    click.echo(f"Instagram success: {stats['ig_success']}")
    click.echo(f"X success: {stats['x_success']}")
    click.echo(f"Threads success: {stats.get('threads_success', 0)}")
    click.echo(f"Errors: {stats['errors']}")

    if stats["errors"] > 0:
        sys.exit(1)


@main.command()
@click.argument("page_id")
@click.option(
    "--platform",
    type=click.Choice(["instagram", "x", "threads", "all"]),
    default="all",
    help="Platform to post to (default: all)",
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
    if "threads_post_id" in result:
        click.echo(f"Threads post ID: {result['threads_post_id']}")


@main.command()
@click.pass_context
def refresh_token(ctx):
    """Refresh the Instagram/Threads access tokens."""
    config = Config.load(ctx.obj.get("env_file"))
    from .r2_storage import R2Storage
    from .token_manager import TokenManager

    r2 = R2Storage(config.r2)

    # 1. Instagram
    tm_ig = TokenManager(r2, config.instagram) # Default key config/instagram_token.json

    click.echo("Refreshing Instagram token...")
    new_token_ig = tm_ig.force_refresh()

    success = True
    if new_token_ig:
        click.echo(f"  Instagram: Success! {new_token_ig[:15]}...")
    else:
        click.echo("  Instagram: Failed.", err=True)
        success = False

    # 2. Threads
    tm_threads = TokenManager(
        r2,
        config.threads,
        token_file_key="config/threads_token.json",
        base_url="https://graph.threads.net",
        api_version=None,
        grant_type="th_refresh_token",
        exchange_param="access_token",
        token_endpoint="refresh_access_token",
        include_client_credentials=False,
        fallback_grant_type="th_exchange_token",
        fallback_exchange_param="access_token",
        fallback_token_endpoint="oauth/access_token",
        fallback_include_client_credentials=True,
    )

    click.echo("Refreshing Threads token...")
    new_token_th = tm_threads.force_refresh()

    if new_token_th:
         click.echo(f"  Threads: Success! {new_token_th[:15]}...")
    else:
         click.echo("  Threads: Failed.", err=True)
         success = False

    if not success:
        sys.exit(1)


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
        if hasattr(work, 'threads_posted') and work.threads_posted:
            status.append("Threads")
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


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--threshold", "-t", default=10, help="Time gap threshold in minutes (default: 10)")
@click.option("--dry-run", is_flag=True, help="Preview organization without moving files")
@click.option("--copy", "-c", is_flag=True, help="Copy files instead of moving them (safer)")
@click.option("--output", "-o", type=click.Path(file_okay=False, path_type=Path), help="Output folder (separate from source)")
@click.pass_context
def organize(ctx, folder: Path, threshold: int, dry_run: bool, copy: bool, output: Path | None):
    """Organize a flat folder of photos into timestamped subfolders."""
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)

    if not dry_run:
        action = "COPY" if copy else "MOVE"
        dest = output if output else folder
        click.confirm(
            f"This will {action} photos in {folder} into subfolders in {dest}. Continue?",
            abort=True,
        )

    stats = importer.organize_folder(folder, threshold_minutes=threshold, dry_run=dry_run, copy=copy, output_folder=output)

    if not dry_run:
        click.echo(f"\nOrganization Complete:")
        click.echo(f"  Folders created: {stats['folders_created']}")
        click.echo(f"  Photos processed: {stats['processed']}")


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--student", "-s", help="Student name for all imported works")
@click.option(
    "--start-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date for scheduling (increments by 1 day per work)",
)
@click.option("--dry-run", is_flag=True, help="Preview import without making changes")
@click.pass_context
def import_folders(ctx, folder: Path, student: str | None, start_date: datetime | None, dry_run: bool):
    """Import each subfolder as a separate work (Work Name = Folder Name)."""
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)

    if not dry_run:
        click.confirm(
            f"This will import all subfolders in {folder} as separate works. Continue?",
            abort=True,
        )

    stats = importer.import_from_subfolders(
        folder,
        student_name=student,
        start_date=start_date,
        dry_run=dry_run,
    )

    if stats["errors"] > 0:
        sys.exit(1)



@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--dry-run", is_flag=True, help="Preview updates without making changes")
@click.pass_context
def update_locations(ctx, folder: Path, dry_run: bool):
    """
    Update Notion entries with location data from local photos.
    Does NOT create new pages, only updates existing ones based on matching Work Name.
    Useful when location data was missing during initial import.
    """
    config = Config.load(ctx.obj.get("env_file"))
    importer = Importer(config)

    folder_path = Path(folder)
    importer.update_existing_locations(folder_path, dry_run=dry_run)


if __name__ == "__main__":
    main()
