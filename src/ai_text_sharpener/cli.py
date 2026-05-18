"""CLI entry point."""
from pathlib import Path

import click

from .fonts import FontSpec
from .pipeline import sharpen_image


@click.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output-png", required=True, type=click.Path(path_type=Path))
@click.option("--svg", "output_svg", type=click.Path(path_type=Path), default=None,
              help="SVG output path (default: <output-png>.svg)")
@click.option("--title-font", default="Microsoft YaHei Bold", show_default=True)
@click.option("--body-font", default="Microsoft YaHei", show_default=True)
@click.option("--title-min-px", default=40, show_default=True, type=int,
              help="Font size threshold (px) for title vs body")
def main(input_path, output_png, output_svg, title_font, body_font, title_min_px):
    """Replace blurry text in an AI-generated image with crisp vector text."""
    if output_svg is None:
        output_svg = output_png.with_suffix(".svg")
    spec = FontSpec(title=title_font, body=body_font, title_min_px=title_min_px)
    click.echo(f"Processing {input_path} ...")
    sharpen_image(input_path, output_png, output_svg, spec)
    click.echo(f"OK -> {output_png}  +  {output_svg}")


if __name__ == "__main__":
    main()
