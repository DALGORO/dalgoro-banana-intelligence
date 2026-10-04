"""CLI aislado para renderizar un tile PNG desde un COG local confiable.

La ruta del COG es server-side y sólo debe ser suministrada por infraestructura
DBI autorizada. El CLI escribe exclusivamente bytes PNG en stdout cuando tiene
éxito y usa códigos de salida estables para errores esperados.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from banana_analyzer.raster_tile_renderer import (  # noqa: E402
    RasterTileOutsideExtent,
    RasterTileRenderError,
    RasterTileStyle,
    render_cog_xyz_tile,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Renderiza un tile XYZ PNG desde un COG local DBI.",
    )
    parser.add_argument("source", help="Ruta local interna del COG")
    parser.add_argument("z", type=int)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument(
        "--render-mode",
        choices=("rgb", "single_band"),
        required=True,
    )
    parser.add_argument("--style-id", required=True)
    parser.add_argument(
        "--bands",
        required=True,
        help="Índices 1-based separados por comas, por ejemplo 1,2,3",
    )
    parser.add_argument("--display-min", type=float, default=None)
    parser.add_argument("--display-max", type=float, default=None)
    parser.add_argument("--tile-size", type=int, choices=(256, 512), default=256)
    return parser


def _bands(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(part) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("bands inválido") from error
    if not result or any(index <= 0 for index in result):
        raise argparse.ArgumentTypeError("bands inválido")
    return result


def main() -> int:
    args = _parser().parse_args()
    try:
        style = RasterTileStyle(
            style_id=args.style_id,
            render_mode=args.render_mode,
            band_indexes=_bands(args.bands),
            display_min=args.display_min,
            display_max=args.display_max,
        )
        rendered = render_cog_xyz_tile(
            args.source,
            z=args.z,
            x=args.x,
            y=args.y,
            style=style,
            tile_size=args.tile_size,
        )
    except RasterTileOutsideExtent:
        return 4
    except (RasterTileRenderError, argparse.ArgumentTypeError):
        return 5
    except Exception:
        return 6

    sys.stdout.buffer.write(rendered.data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
