"""
reduce_image_size.py — PNG image reducer: dimensions and/or file weight.

DESCRIPTION:
    Two independent reduction modes, both optional (but at least one required):

    --resize WxH
        Scales image to exact pixel dimensions using bilinear interpolation.
        Example: --resize 320x240  (width x height)

    --weight PERCENTAGE
        Reduces file size (bytes) without changing pixel dimensions.
        100 = no reduction, 50 = moderate compression + color quantization,
        1 = maximum compression + aggressive color quantization.
        Achieved via PNG compression level and palette quantization.

    Output is saved next to the original with '_reduced' appended
    (e.g. photo.png -> photo_reduced.png).

USAGE:
    python reduce_image_size.py <path_to_png> [--resize WxH] [--weight N]

EXAMPLES:
    # Resize to exact dimensions only
    python reduce_image_size.py C:\\images\\photo.png --resize 320x240

    # Reduce file weight to ~50% without changing dimensions
    python reduce_image_size.py C:\\images\\photo.png --weight 50

    # Both: resize to exact dimensions AND reduce file weight aggressively
    python reduce_image_size.py C:\\images\\photo.png --resize 320x240 --weight 20

REQUIREMENTS:
    pip install Pillow
"""

import argparse
import os
import sys
from pathlib import Path
from PIL import Image


def reduce_image(input_path: str, resize: tuple | None, weight: int) -> None:
    src = Path(input_path)
    if not src.exists():
        print(f"Error: file not found: {src}")
        sys.exit(1)
    if src.suffix.lower() != ".png":
        print(f"Error: file must be a PNG, got: {src.suffix}")
        sys.exit(1)

    with Image.open(src) as img:
        orig_w, orig_h = img.size
        orig_bytes = os.path.getsize(src)

        # --- Step 1: resize dimensions ---
        if resize is not None:
            new_w, new_h = resize
            img = img.resize((new_w, new_h), Image.BILINEAR)
        else:
            new_w, new_h = orig_w, orig_h

        # --- Step 2: reduce file weight ---
        # compress_level: 0 (no compression) to 9 (max). We invert weight so
        # lower weight% = higher compression level.
        compress_level = round(9 * (1 - weight / 100))  # 100%->0, 1%->~9

        # Below 60% weight, also quantize colors to shrink palette.
        if weight < 60:
            if img.mode in ("RGBA",):
                # Quantize with alpha: convert to P mode keeping transparency
                num_colors = max(8, round(256 * weight / 60))
                img = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
            else:
                num_colors = max(8, round(256 * weight / 60))
                img = img.convert("RGB").quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
        else:
            num_colors = None

        out_path = src.with_stem(src.stem + "_reduced")
        img.save(out_path, format="PNG", optimize=True, compress_level=compress_level)

    out_bytes = os.path.getsize(out_path)
    print(f"Input:    {src}")
    print(f"          {orig_w}x{orig_h}  |  {orig_bytes:,} bytes")
    print(f"Output:   {out_path}")
    print(f"          {new_w}x{new_h}  |  {out_bytes:,} bytes  ({out_bytes*100//orig_bytes}% of original)")
    if resize is not None:
        print(f"  Resize: {resize[0]}x{resize[1]} px")
    if weight != 100:
        print(f"  Weight: {weight}%  (compress_level={compress_level}"
              + (f", quantized to {num_colors} colors)" if num_colors else ")"))


def main():
    parser = argparse.ArgumentParser(
        description="Reduce PNG image dimensions and/or file weight.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", help="Absolute path to the PNG file.")
    parser.add_argument(
        "--resize",
        type=str,
        default=None,
        metavar="WxH",
        help="Resize to exact pixel dimensions, e.g. --resize 320x240.",
    )
    parser.add_argument(
        "--weight",
        type=int,
        default=100,
        metavar="N",
        help="Reduce file weight to approximately N%% via compression + quantization (1-100, default: 100).",
    )
    args = parser.parse_args()

    if args.resize is None and args.weight == 100:
        print("Error: provide at least one of --resize or --weight.")
        sys.exit(1)

    resize = None
    if args.resize is not None:
        try:
            parts = args.resize.lower().split("x")
            if len(parts) != 2:
                raise ValueError
            resize = (int(parts[0]), int(parts[1]))
            if resize[0] < 1 or resize[1] < 1:
                raise ValueError
        except ValueError:
            print("Error: --resize must be in WxH format with positive integers, e.g. 320x240.")
            sys.exit(1)

    if not 1 <= args.weight <= 100:
        print("Error: --weight must be between 1 and 100.")
        sys.exit(1)

    reduce_image(args.path, resize, args.weight)


if __name__ == "__main__":
    main()
