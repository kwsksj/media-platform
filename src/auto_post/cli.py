"""Command-line interface."""

import logging
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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
# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@dataclass
class MonthlyScheduleItem:
    year: int
    month: int
    caption_entries: list[Any]
    image: Any


def _parse_skip_target_months(raw: str) -> set[tuple[int, int]]:
    months: set[tuple[int, int]] = set()
    text = str(raw or "").strip()
    if not text:
        return months
    for token in re.split(r"[,\s]+", text):
        value = token.strip()
        if not value:
            continue
        match = re.fullmatch(r"(\d{4})[-/](\d{1,2})", value)
        if not match:
            raise click.ClickException(
                "MONTHLY_SCHEDULE_SKIP_TARGET_MONTHS has invalid token: "
                f"{value} (expected YYYY-MM, separated by comma or space)"
            )
        year = int(match.group(1))
        month = int(match.group(2))
        if not 1 <= month <= 12:
            raise click.ClickException(
                "MONTHLY_SCHEDULE_SKIP_TARGET_MONTHS has invalid month: "
                f"{value} (month must be 1-12)"
            )
        months.add((year, month))
    return months


def _shift_year_month(base_year: int, base_month: int, add: int) -> tuple[int, int]:
    total = base_year * 12 + (base_month - 1) + add
    return total // 12, (total % 12) + 1


def _build_monthly_output_path(base_output: Path, index: int, year: int, month: int) -> Path:
    if index == 0:
        return base_output
    suffix = base_output.suffix or ".jpg"
    return base_output.with_name(f"{base_output.stem}-{year}-{month:02d}{suffix}")


def _build_monthly_schedule_loader(source: str, config: Config) -> Callable[[int, int], list[Any]]:
    from .monthly_schedule import (
        MonthlyScheduleNotionClient,
        ScheduleJsonSourceConfig,
        ScheduleSourceConfig,
        extract_month_entries_from_json,
    )
    from .r2_storage import R2Storage

    if source in {"r2-json", "json", "r2"}:
        json_source = ScheduleJsonSourceConfig.from_env()
        if json_source.url:
            import requests

            try:
                res = requests.get(json_source.url, timeout=30)
                res.raise_for_status()
                data = res.json()
            except Exception as e:
                raise click.ClickException(f"Failed to fetch MONTHLY_SCHEDULE_JSON_URL: {e}") from e
        else:
            r2 = R2Storage(config.r2)
            data = r2.get_json(json_source.key)
            if data is None:
                raise click.ClickException(f"R2 JSON not found: key={json_source.key}")

        if not isinstance(data, dict):
            raise click.ClickException("Schedule JSON must be an object")

        def load_month_entries(y: int, m: int) -> list[Any]:
            return extract_month_entries_from_json(
                data,
                y,
                m,
                timezone=json_source.timezone,
                include_adjacent=True,
            )

        return load_month_entries

    if source == "notion":
        try:
            source_config = ScheduleSourceConfig.from_env()
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        schedule_client = MonthlyScheduleNotionClient(config.notion.token, source_config)

        def load_month_entries(y: int, m: int) -> list[Any]:
            return schedule_client.fetch_month_entries(y, m, include_adjacent=True)

        return load_month_entries

    raise click.ClickException("MONTHLY_SCHEDULE_SOURCE must be one of: r2-json, json, r2, notion")


def _prepare_monthly_schedule_images(
    month_items: list[MonthlyScheduleItem],
    output: Path | None,
    *,
    default_schedule_filename: Callable[[int, int, str], str],
    image_to_bytes: Callable[[Any, str], bytes],
    save_image: Callable[[Any, Path], str],
) -> tuple[list[tuple[bytes, str, str]], list[Path]]:
    images_data: list[tuple[bytes, str, str]] = []
    saved_outputs: list[Path] = []

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)

    for index, item in enumerate(month_items):
        post_mime_type = "image/jpeg"
        post_filename = default_schedule_filename(item.year, item.month, post_mime_type)

        if output:
            output_path = _build_monthly_output_path(output, index, item.year, item.month)
            save_image(item.image, output_path)
            saved_outputs.append(output_path)

        image_bytes = image_to_bytes(item.image, post_mime_type)
        images_data.append((image_bytes, post_filename, post_mime_type))

    return images_data, saved_outputs


def _merge_post_result(target: dict, partial: dict) -> None:
    for key in ("instagram", "threads", "x"):
        target[key] = bool(target[key] or partial.get(key))
    target["post_ids"].update(partial.get("post_ids", {}))
    target["errors"].extend(partial.get("errors", []))


def _echo_monthly_schedule_summary(
    *,
    target_year: int,
    target_month: int,
    source: str,
    month_items: list[MonthlyScheduleItem],
    render_width: int,
    render_height: int,
    saved_outputs: list[Path],
    result: dict,
) -> None:
    click.echo("\n" + "=" * 34)
    click.echo("Monthly Schedule Post Summary")
    click.echo("=" * 34)
    click.echo(f"Target month: {target_year}-{target_month:02d}")
    click.echo(
        "Posted months: "
        + ", ".join([f"{item.year}-{item.month:02d}" for item in month_items])
    )
    click.echo(f"Source: {source}")
    for item in month_items:
        click.echo(f"Entries {item.year}-{item.month:02d}: {len(item.caption_entries)}")
    click.echo(f"Image size: {render_width}x{render_height} (3:4 expected)")
    if saved_outputs:
        if len(saved_outputs) == 1:
            click.echo(f"Saved image: {saved_outputs[0]}")
        else:
            click.echo("Saved images:")
            for path in saved_outputs:
                click.echo(f"  - {path}")
    click.echo(f"Instagram: {'OK' if result['instagram'] else '-'}")
    click.echo(f"Threads:   {'OK' if result['threads'] else '-'}")
    click.echo(f"X:         {'OK' if result['x'] else '-'}")
    if result.get("post_ids"):
        post_ids = result["post_ids"]
        click.echo(f"Post IDs:  {post_ids}")
    if result["errors"]:
        click.echo("-" * 34)
        click.echo("Errors:")
        for err in result["errors"]:
            click.echo(f"  - {err}")
        click.echo("=" * 34)
        sys.exit(1)
    click.echo("=" * 34)


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
@click.option("--basic-limit", "-b", default=2, help="Number of basic posts per platform (default: 2)")
@click.option("--catchup-limit", "-c", default=1, help="Number of catch-up posts per platform (default: 1)")
@click.pass_context
def post(ctx, date: datetime | None, dry_run: bool, platform: str, basic_limit: int, catchup_limit: int):
    """Run the daily posting job."""
    config = Config.load(ctx.obj.get("env_file"))
    poster = Poster(config)

    target_date = date or datetime.now()

    # Convert platform arg to list
    if platform == "all":
        platforms = ["instagram", "threads", "x"]  # X is now included
    else:
        platforms = [platform]

    stats = poster.run_daily_post(
        target_date,
        dry_run=dry_run,
        platforms=platforms,
        basic_limit=basic_limit,
        catchup_limit=catchup_limit,
    )

    click.echo("\n" + "=" * 30)
    click.echo("Daily Post Summary")
    click.echo("=" * 30)
    click.echo(f"Processed ({len(stats['processed'])}): {', '.join(stats['processed'])}")
    click.echo(f"Instagram ({len(stats['ig_success'])}): {', '.join(stats['ig_success'])}")
    click.echo(f"Threads   ({len(stats.get('threads_success', []))}): {', '.join(stats.get('threads_success', []))}")
    click.echo(f"X         ({len(stats['x_success'])}): {', '.join(stats['x_success'])}")

    if stats['errors']:
        click.echo("-" * 30)
        click.echo(f"Errors    ({len(stats['errors'])}): {'; '.join(stats['errors'])}")
    else:
        click.echo("Errors    (0)")
    click.echo("=" * 30)

    if len(stats["errors"]) > 0:
        sys.exit(1)


@main.command()
@click.option("--limit", "-n", default=1, help="Number of posts per platform (default: 1)")
@click.option("--dry-run", is_flag=True, help="Preview without executing")
@click.option(
    "--platform",
    "-p",
    type=click.Choice(["instagram", "x", "threads", "all"]),
    default="all",
    help="Target platform (default: all)",
)
@click.pass_context
def catchup(ctx, limit: int, dry_run: bool, platform: str):
    """Run catch-up posts only."""
    config = Config.load(ctx.obj.get("env_file"))
    poster = Poster(config)

    # Convert platform arg to list
    if platform == "all":
        platforms = ["instagram", "threads", "x"]
    else:
        platforms = [platform]

    stats = poster.run_catchup_post(limit=limit, dry_run=dry_run, platforms=platforms)

    click.echo("\n" + "=" * 30)
    click.echo("Catch-up Post Summary")
    click.echo("=" * 30)
    click.echo(f"Processed ({len(stats['processed'])}): {', '.join(stats['processed'])}")
    click.echo(f"Instagram ({len(stats['ig_success'])}): {', '.join(stats['ig_success'])}")
    click.echo(f"Threads   ({len(stats.get('threads_success', []))}): {', '.join(stats.get('threads_success', []))}")
    click.echo(f"X         ({len(stats['x_success'])}): {', '.join(stats['x_success'])}")

    if stats['errors']:
        click.echo("-" * 30)
        click.echo(f"Errors    ({len(stats['errors'])}): {'; '.join(stats['errors'])}")
    else:
        click.echo("Errors    (0)")
    click.echo("=" * 30)

    if len(stats["errors"]) > 0:
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
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write gallery.json to a local file",
)
@click.option("--no-upload", is_flag=True, help="Skip uploading gallery.json to R2")
@click.option("--no-thumbs", is_flag=True, help="Skip generating thumbnails")
@click.option("--thumb-width", default=600, show_default=True, help="Thumbnail width in px")
@click.option("--no-light", is_flag=True, help="Skip generating light images")
@click.option("--light-max-size", default=1600, show_default=True, help="Max size for light images in px")
@click.option("--light-quality", default=75, show_default=True, help="JPEG quality for light images")
@click.option("--overwrite-thumbs", is_flag=True, help="Regenerate thumbnails even if they exist")
@click.option("--overwrite-light", is_flag=True, help="Regenerate light images even if they exist")
@click.pass_context
def export_gallery_json(
    ctx,
    output: Path | None,
    no_upload: bool,
    no_thumbs: bool,
    thumb_width: int,
    no_light: bool,
    light_max_size: int,
    light_quality: int,
    overwrite_thumbs: bool,
    overwrite_light: bool,
):
    """Export gallery.json from Notion and upload to R2."""
    config = Config.load(ctx.obj.get("env_file"), allow_missing_instagram=True)
    from .gallery_exporter import GalleryExporter

    exporter = GalleryExporter(config)
    _, stats = exporter.export(
        output_path=output,
        upload=not no_upload,
        generate_thumbs=not no_thumbs,
        thumb_width=thumb_width,
        generate_light_images=not no_light,
        light_max_size=light_max_size,
        light_quality=light_quality,
        overwrite_thumbs=overwrite_thumbs,
        overwrite_light_images=overwrite_light,
    )

    click.echo("\n" + "=" * 30)
    click.echo("Gallery Export Summary")
    click.echo("=" * 30)
    click.echo(f"Total pages: {stats.total_pages}")
    click.echo(f"Exported:    {stats.exported}")
    click.echo(f"Skip (not ready): {stats.skipped_not_ready}")
    click.echo(f"Skip (no images): {stats.skipped_no_images}")
    click.echo(f"Skip (no completed_date): {stats.skipped_no_completed_date}")
    if not no_thumbs:
        click.echo(f"Thumbs generated: {stats.thumb_generated}")
        click.echo(f"Thumbs existing:  {stats.thumb_skipped_existing}")
        click.echo(f"Thumbs failed:    {stats.thumb_failed}")
    if not no_light:
        click.echo(f"Light generated:  {stats.light_generated}")
        click.echo(f"Light existing:   {stats.light_skipped_existing}")
        click.echo(f"Light failed:     {stats.light_failed}")
    click.echo("=" * 30)


@main.command("post-monthly-schedule")
@click.option("--year", type=int, help="Target year (e.g. 2026)")
@click.option("--month", type=click.IntRange(1, 12), help="Target month (1-12)")
@click.option(
    "--target",
    type=click.Choice(["current", "next"]),
    default=None,
    help="When year/month are omitted, post current or next month",
)
@click.option(
    "--platform",
    type=click.Choice(["instagram", "x", "threads", "all"]),
    default="all",
    help="Platform to post to (default: all)",
)
@click.option("--dry-run", is_flag=True, help="Generate image and caption without posting")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Optional output path to save generated image (.jpg/.png)",
)
@click.pass_context
def post_monthly_schedule(
    ctx,
    year: int | None,
    month: int | None,
    target: str | None,
    platform: str,
    dry_run: bool,
    output: Path | None,
):
    """Generate monthly schedule image from JSON/R2 and post to SNS."""
    config = Config.load(ctx.obj.get("env_file"))
    from .monthly_schedule import (
        JST,
        ScheduleRenderConfig,
        build_monthly_caption,
        default_schedule_filename,
        image_to_bytes,
        render_monthly_schedule_image,
        resolve_target_year_month,
        save_image,
    )

    env_target = os.environ.get("MONTHLY_SCHEDULE_TARGET", "next").strip().lower()
    if env_target not in {"current", "next"}:
        env_target = "next"
    resolved_target = target or env_target

    try:
        target_year, target_month = resolve_target_year_month(
            now=datetime.now(tz=JST),
            target=resolved_target,
            year=year,
            month=month,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    skip_targets_raw = os.environ.get("MONTHLY_SCHEDULE_SKIP_TARGET_MONTHS", "").strip()
    skip_targets = _parse_skip_target_months(skip_targets_raw)
    if (target_year, target_month) in skip_targets:
        click.echo("\n" + "=" * 34)
        click.echo("Monthly Schedule Post Summary")
        click.echo("=" * 34)
        click.echo(f"Target month: {target_year}-{target_month:02d}")
        click.echo("Result: SKIPPED")
        click.echo(f"Reason: MONTHLY_SCHEDULE_SKIP_TARGET_MONTHS={skip_targets_raw}")
        click.echo("=" * 34)
        return

    source = os.environ.get("MONTHLY_SCHEDULE_SOURCE", "").strip().lower() or "r2-json"
    render_config = ScheduleRenderConfig.from_env()
    target_months = [_shift_year_month(target_year, target_month, offset) for offset in range(3)]
    month_items: list[MonthlyScheduleItem] = []
    load_month_entries = _build_monthly_schedule_loader(source, config)

    for y, m in target_months:
        render_entries = load_month_entries(y, m)

        caption_entries = [e for e in render_entries if e.day.year == y and e.day.month == m]
        if not caption_entries:
            continue

        image = render_monthly_schedule_image(y, m, render_entries, render_config)
        month_items.append(
            MonthlyScheduleItem(
                year=y,
                month=m,
                caption_entries=caption_entries,
                image=image,
            )
        )

    if not month_items:
        end_year, end_month = target_months[-1]
        raise click.ClickException(
            f"No schedule entries found from {target_year}-{target_month:02d} to {end_year}-{end_month:02d}"
        )

    images_data, saved_outputs = _prepare_monthly_schedule_images(
        month_items,
        output,
        default_schedule_filename=default_schedule_filename,
        image_to_bytes=image_to_bytes,
        save_image=save_image,
    )

    caption_template = os.environ.get("MONTHLY_SCHEDULE_CAPTION_TEMPLATE", "").strip()
    monthly_schedule_tags = ""
    first_item = month_items[0]
    first_year = first_item.year
    first_month = first_item.month
    first_entries = first_item.caption_entries
    merged_entries = [entry for item in month_items for entry in item.caption_entries]

    if len(month_items) > 1:
        last_item = month_items[-1]
        last_year = last_item.year
        last_month = last_item.month
        if first_year == last_year:
            range_label = f"{first_year}年{first_month}月〜{last_month}月"
        else:
            range_label = f"{first_year}年{first_month}月〜{last_year}年{last_month}月"
        multi_template = (
            f"{range_label}の教室日程です。\n"
            "最新の空き状況や詳細は予約ページをご確認ください。"
        )
        caption_for_ig_threads = build_monthly_caption(
            first_year,
            first_month,
            merged_entries,
            default_tags=monthly_schedule_tags,
            template=multi_template,
        )
    else:
        caption_for_ig_threads = build_monthly_caption(
            first_year,
            first_month,
            first_entries,
            default_tags=monthly_schedule_tags,
            template=caption_template,
        )

    caption_for_x = build_monthly_caption(
        first_year,
        first_month,
        first_entries,
        default_tags=monthly_schedule_tags,
        template=caption_template,
    )

    if platform == "all":
        platforms = ["instagram", "threads", "x"]
    else:
        platforms = [platform]

    poster = Poster(config)
    result = {"instagram": False, "x": False, "threads": False, "post_ids": {}, "errors": []}

    ig_threads_platforms = [p for p in platforms if p in {"instagram", "threads"}]
    if ig_threads_platforms:
        ig_threads_result = poster.post_custom_images(
            images_data=images_data,
            caption=caption_for_ig_threads,
            dry_run=dry_run,
            platforms=ig_threads_platforms,
        )
        _merge_post_result(result, ig_threads_result)

    if "x" in platforms:
        x_result = poster.post_custom_images(
            images_data=[images_data[0]],
            caption=caption_for_x,
            dry_run=dry_run,
            platforms=["x"],
        )
        _merge_post_result(result, x_result)

    _echo_monthly_schedule_summary(
        target_year=target_year,
        target_month=target_month,
        source=source,
        month_items=month_items,
        render_width=render_config.width,
        render_height=render_config.height,
        saved_outputs=saved_outputs,
        result=result,
    )


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
        click.echo("\nOrganization Complete:")
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
