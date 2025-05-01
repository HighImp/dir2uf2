#!/usr/bin/env python3

import os
import math
import argparse
import struct
import pathlib
import logging
from typing import Generator, List, Tuple, Union
import littlefs
from dir2uf2.py_decl import PyDecl, UF2Reader

# UF2 file format constants
UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157  # Randomly selected
UF2_MAGIC_END    = 0x0AB16F30  # Ditto
FS_START_ADDR    = 0x1012c000  # Pico W MicroPython LFSV2 offset
FS_SIZE          = 848 * 1024

# UF2 family IDs
FAMILY_ID_RP2040 = 0xe48bff56  # RP2040
FAMILY_ID_PAD    = 0xe48bff57  # ???
FAMILY_ID_RP2350 = 0xe48bff59  # RP2350

RP_FLASH_BLOCK_SIZE = 4096

BLOCK_SIZE = 512
DATA_SIZE = 256
HEADER_SIZE = 32
FOOTER_SIZE = 4
PADDING_SIZE = BLOCK_SIZE - DATA_SIZE - HEADER_SIZE - FOOTER_SIZE
DATA_PADDING = b"\x00" * PADDING_SIZE

def copy_files(lfs, todo, source_dir, verbose=False):
    """Copy files from source dir into the lfs, filter by todo list"""
    log = logging.getLogger(__name__)
    for src in todo:
        if src.is_dir():
            dst = src.relative_to(source_dir)
            if verbose:
                log.debug(f"- mkdir: {dst}")
            lfs.makedirs(dst.as_posix().replace("\\", "/"), exist_ok=True)
        if src.is_file():
            dst = src.relative_to(source_dir)
            if verbose:
                log.debug(f"- copy: {src} to {dst}")
            with lfs.open(dst.as_posix().replace("\\", "/"), "wb") as outfile:
                with open(src, "rb") as infile:
                    outfile.write(infile.read())


def copy_manifest_or_dir(lfs, source_dir, manifest=None):
    """Copy files from source dir into the lfs, optionally filtered by manifest"""
    log = logging.getLogger(__name__)
    if manifest is None:
        log.info(f"Copying directory: {source_dir}")
        # Walk the entire source dir and copy *everything*
        search_path = os.path.join("**", "*")
        copy_files(lfs, source_dir.glob(search_path), source_dir)

    else:
        log.info(f"Using manifest: {manifest}")
        # Copy files/globs listed in the manifest relative to the source dir
        todo = [line.strip() for line in open(manifest, "r").readlines() if line.strip()]
        for item in todo:
            parent_dir = pathlib.Path(item).parent
            lfs.makedirs(str(parent_dir), exist_ok=True)
            copy_files(lfs, source_dir.glob(item), source_dir)


def uf2_to_bin(data: bytes) -> Generator:
    """Convert UF2 data to binary sections.
    
    :param bytes data: Raw UF2 file data
    """
    section_index = 0
    for offset in range(0, len(data), BLOCK_SIZE):
        start0, start1, flags, addr, size, block_no, num_blocks, family_id = struct.unpack(
            b"<IIIIIIII", data[offset:offset + HEADER_SIZE])

        if block_no == 0:
            yield section_index, addr, family_id, flags, num_blocks, uf2_section_data(data[offset:])
            section_index += 1

def uf2_section_data(data: bytes) -> Generator:
    """Extract data from a UF2 section.
    
    :param bytes data: Raw UF2 section data
    """
    log = logging.getLogger(__name__)
    for offset in range(0, len(data), BLOCK_SIZE):
        start0, start1, flags, addr, size, block_no, num_blocks, family_id = struct.unpack(
            b"<IIIIIIII", data[offset:offset + HEADER_SIZE])

        if block_no == 0 and offset >= BLOCK_SIZE:
            break

        log.debug(f"Block {block_no}/{num_blocks} addr {addr:08x} size {size}")

        yield addr, data[offset + HEADER_SIZE:offset + HEADER_SIZE + DATA_SIZE]

def bin_to_uf2(sections: List[Tuple[Union[int, List], Union[bytes, List], int, int]]) -> Generator[bytes, None, None]:
    """Convert binary sections to UF2 format.
    
    :param List[Tuple[Union[int, List], Union[bytes, List], int, int]] sections: List of (offsets, data, family_id, flags) tuples
    """
    log = logging.getLogger(__name__)
    for section in sections:
        offsets, datas, family_id, flags = section

        if not isinstance(offsets, (list, tuple)):
            offsets = (offsets, )
            datas = (datas, )

        total_blocks = sum([(len(data) + (DATA_SIZE - 1)) // DATA_SIZE for data in datas])

        # HACK: If we don't use "num_blocks + 1" then the 0xe48bff57
        # section at the top of RP2350 UF2 files will have a block count
        # of 1 and simply not flash, at all. I don't know why this is.
        if family_id == FAMILY_ID_PAD:
            total_blocks += 1

        block_no = 0

        for i in range(len(offsets)):
            offset = offsets[i]
            data = datas[i]

            num_blocks = (len(data) + (DATA_SIZE - 1)) // DATA_SIZE

            log.debug(f"uf2: Adding {len(data)} bytes at 0x{offset:08x}")

            for block_index in range(num_blocks):
                ptr = DATA_SIZE * block_index

                chunk = data[ptr:ptr + DATA_SIZE].rjust(DATA_SIZE, b"\x00")
                header = struct.pack(
                    b"<IIIIIIII",
                    UF2_MAGIC_START0, UF2_MAGIC_START1, flags,
                    ptr + offset, DATA_SIZE, block_no, total_blocks,
                    family_id)

                footer = struct.pack(b"<I", UF2_MAGIC_END)

                block = header + chunk + DATA_PADDING + footer

                block_no += 1

                if len(block) != BLOCK_SIZE:
                    raise RuntimeError(f"Invalid block size: {len(block)} != {BLOCK_SIZE}")

                yield block

def append_to_uf2(
    append_to: pathlib.Path,
    lfs_data: bytes,
    output_filename: pathlib.Path,
    fs_start: int,
    fs_overwrite: bool,
    sparse: bool
) -> None:
    """Append filesystem to an existing UF2 file.
    
    :param append_to: Path to the UF2 file to append to
    :param bytes lfs_data: Filesystem data to append
    :param pathlib.Path output_filename: Path to output file
    :param int fs_start: Filesystem start address
    :param bool fs_overwrite: Whether to overwrite existing filesystem
    :param bool sparse: Whether to use sparse filesystem
    """
    log = logging.getLogger(__name__)
    
    if not append_to.is_file():
        raise FileNotFoundError(f"Could not find {append_to}")

    uf2_append_filename = output_filename.with_name(f"{append_to.stem}-{output_filename.stem}.uf2")
    log.info(f"Appending to {append_to}")

    output_sections = []

    with open(uf2_append_filename, "wb") as f:
        append_to_data = open(append_to, "rb").read()
        sections = uf2_to_bin(append_to_data)
        current_fs_start = fs_start

        for section in sections:
            section_index, start_addr, family_id, flags, num_blocks, block_data = section
            block_data = list(block_data)

            # Check for filesystem overlap
            block_addresses = map(lambda b: b[0], block_data)
            if fs_start in block_addresses and not fs_overwrite:
                raise RuntimeError("Trying to append over an existing filesystem!")

            # Filter out blocks that would be overwritten
            block_data = b"".join(b[1] for b in block_data if b[0] < fs_start)

            if family_id in (FAMILY_ID_RP2040, FAMILY_ID_RP2350):
                if sparse:
                    # Handle sparse filesystem
                    fw_size = len(block_data)
                    fw_size = math.ceil(fw_size / float(RP_FLASH_BLOCK_SIZE)) * RP_FLASH_BLOCK_SIZE
                    block_data = block_data.ljust(fw_size, b"\xff")

                    current_fs_start -= start_addr
                    current_fs_start = math.ceil(current_fs_start / float(RP_FLASH_BLOCK_SIZE)) * RP_FLASH_BLOCK_SIZE
                    current_fs_start += start_addr
                    fs_padding = current_fs_start - fs_start

                    lfs_data = lfs_data.rjust(len(lfs_data) + fs_padding, b"\xff")

                    output_sections.append((
                        (start_addr, current_fs_start),
                        (block_data, lfs_data),
                        family_id,
                        flags
                    ))
                else:
                    # Handle non-sparse filesystem
                    fw_size = fs_start - start_addr
                    block_data = block_data.ljust(fw_size, b"\xff")
                    output_sections.append((
                        start_addr,
                        block_data + lfs_data,
                        family_id,
                        flags
                    ))
            else:
                output_sections.append((
                    start_addr,
                    block_data,
                    family_id,
                    flags
                ))

        # Write the final UF2 file
        for block in bin_to_uf2(output_sections):
            f.write(block)

        log.info(f"Written: {uf2_append_filename}")

def main(args=None):
    """Main entry point for dir2uf2.
    
    :param args: Optional pre-configured args object. If None, will parse command line arguments.
    """
    if args is None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--filename", type=pathlib.Path, default="filesystem", help="Output filename.")
        parser.add_argument("--fs-start", type=int, default=None, help="Filesystem offset.")
        parser.add_argument("--fs-size", type=int, default=None, help="Filesystem size.")
        parser.add_argument("--fs-compact", action="store_true", help="Compact filesystem to used blocks.")
        parser.add_argument("--fs-overwrite", action="store_true", help="Replace an existing filesystem in the UF2.")
        parser.add_argument("--sparse", action="store_true", help="Skip padding between app and filesystem.")
        parser.add_argument("--block-size", type=int, default=4096, help="LFS block size in Kb.")
        parser.add_argument("--read-size", type=int, default=256, help="LFS read size in Kb.")
        parser.add_argument("--prog-size", type=int, default=32, help="LFS prog size in Kb.")
        parser.add_argument("--manifest", default=None, help="Manifest to filter copied files.")
        parser.add_argument("--append-to", type=pathlib.Path, default=None, help="uf2 file to append filesystem.")
        parser.add_argument("--write-bin", action="store_true", help="Write bin file")
        parser.add_argument("--verbose-level", type=str, default="INFO", help="Verbose level (DEBUG, INFO, WARNING, ERROR).")
        parser.add_argument("source_dir", type=pathlib.Path, help="Source directory.")
        args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        format='%(message)s',
        level=logging.getLevelNamesMapping()[args.verbose_level]
    )
    log = logging.getLogger(__name__)

    # Validate input directory
    if not args.source_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {args.source_dir}")

    # Determine filesystem parameters
    output_filename = args.filename
    if args.fs_start is None or args.fs_size is None:
        if args.append_to is None:
            raise ValueError("Either an --append-to UF2 file or explicit --fs-start and --fs-size required!")

        if not args.append_to.is_file():
            raise FileNotFoundError(f"Could not find {args.append_to}")

        # Parse the append-to UF2 file to get the filesystem start and size
        py_decl = PyDecl(UF2Reader(args.append_to))
        parsed = py_decl.parse()
        block_devices = parsed.get("BlockDevice", [])
        for block_device in block_devices:
            args.fs_start = block_device.get("address")
            args.fs_size = block_device.get("size")
            log.info(f"Auto detected fs: 0x{args.fs_start:08x} ({args.fs_start}), {args.fs_size} bytes.")
            break

    # Validate filesystem size
    block_count = math.ceil(args.fs_size / args.block_size)
    if block_count * args.block_size != args.fs_size:
        raise ValueError(f"Filesystem size {args.fs_size} must be a multiple of block size {args.block_size}")

    # Create filesystem
    lfs = littlefs.LittleFS(
        block_size=args.block_size,
        block_count=block_count,
        read_size=args.read_size,
        prog_size=args.prog_size,
    )

    # Copy files
    copy_manifest_or_dir(lfs, args.source_dir, args.manifest)

    # Handle filesystem compaction if requested
    if args.fs_compact:
        lfs_used_bytes = lfs.used_block_count * args.block_size
        log.info(f"Compacting LittleFS to {lfs_used_bytes / 1024}K.")

        lfs_compact = littlefs.LittleFS(
            block_size=args.block_size,
            block_count=lfs.used_block_count,
            read_size=args.read_size,
            prog_size=args.prog_size,
        )

        copy_manifest_or_dir(lfs_compact, args.source_dir)
        lfs_compact.fs_grow(block_count)
        lfs_data = lfs_compact.context.buffer
    else:
        lfs_data = lfs.context.buffer

    # Write binary file if requested
    if args.write_bin:
        bin_filename = output_filename.with_suffix(".bin")
        with open(bin_filename, "wb") as f:
            f.write(lfs_data)
        log.info(f"Written: {bin_filename}")


    # Write a .uf2 with *just* the filesystem
    uf2_filename = output_filename.with_suffix(".uf2")
    with open(uf2_filename, "wb") as f:
        for block in bin_to_uf2([(args.fs_start, lfs_data, FAMILY_ID_RP2040, 0x2000)]):
            f.write(block)
    log.info(f"Written: {uf2_filename}")

    # Append to existing UF2 if requested
    if args.append_to is not None:
        append_to_uf2(
            append_to=args.append_to,
            lfs_data=lfs_data,
            output_filename=output_filename,
            fs_start=args.fs_start,
            fs_overwrite=args.fs_overwrite,
            sparse=args.sparse
        )


if __name__ == "__main__":
    main()