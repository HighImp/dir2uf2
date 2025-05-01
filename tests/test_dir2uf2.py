import os
import tempfile
from pathlib import Path
import pytest
import logging
import argparse
import littlefs
from dir2uf2.dir2uf2 import (
    uf2_to_bin,
    uf2_section_data,
    bin_to_uf2,
    copy_files,
    copy_manifest_or_dir,
    append_to_uf2,
    main,
    # Import constants
    UF2_MAGIC_START0,
    UF2_MAGIC_START1,
    UF2_MAGIC_END,
    BLOCK_SIZE,
    DATA_SIZE,
    HEADER_SIZE,
    FOOTER_SIZE,
    PADDING_SIZE
)

@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def sample_uf2_data():
    """Create sample UF2 data for testing."""
    # Create a simple UF2 block
    data = b"Test data" + b"\x00" * (DATA_SIZE - len(b"Test data"))
    header = (
        UF2_MAGIC_START0.to_bytes(4, 'little') +
        UF2_MAGIC_START1.to_bytes(4, 'little') +
        (0x2000).to_bytes(4, 'little') +  # flags
        (0x1000).to_bytes(4, 'little') +  # target_addr
        DATA_SIZE.to_bytes(4, 'little') +  # payload_size
        (0).to_bytes(4, 'little') +       # block_no
        (1).to_bytes(4, 'little') +       # num_blocks
        (0xe48bff56).to_bytes(4, 'little')  # family_id (RP2040)
    )
    footer = UF2_MAGIC_END.to_bytes(4, 'little')
    padding = b"\x00" * PADDING_SIZE
    
    return header + data + padding + footer

@pytest.fixture
def lfs():
    """Create a LittleFS instance for testing."""
    return littlefs.LittleFS(
        block_size=4096,
        block_count=100,
        read_size=256,
        prog_size=256,
    )

def test_uf2_to_bin(sample_uf2_data):
    """Test UF2 to binary conversion."""
    sections = list(uf2_to_bin(sample_uf2_data))
    assert len(sections) == 1
    section_index, addr, family_id, flags, num_blocks, block_data = sections[0]
    assert section_index == 0
    assert addr == 0x1000
    assert family_id == 0xe48bff56
    assert flags == 0x2000
    assert num_blocks == 1

def test_uf2_section_data(sample_uf2_data):
    """Test UF2 section data extraction."""
    data = list(uf2_section_data(sample_uf2_data))
    assert len(data) == 1
    addr, content = data[0]
    assert addr == 0x1000
    assert content.startswith(b"Test data")

def test_bin_to_uf2():
    """Test binary to UF2 conversion."""
    sections = [(0x1000, b"Test data", 0xe48bff56, 0x2000)]
    uf2_data = b"".join(bin_to_uf2(sections))
    
    # Verify UF2 structure
    assert uf2_data.startswith(UF2_MAGIC_START0.to_bytes(4, 'little'))
    assert UF2_MAGIC_END.to_bytes(4, 'little') in uf2_data
    assert b"Test data" in uf2_data

def test_copy_files(temp_dir, lfs):
    """Test file copying functionality."""
    # Create source directory with test files
    src_dir = temp_dir / "src"
    src_dir.mkdir()
    (src_dir / "test.txt").write_text("Test content")
    (src_dir / "subdir").mkdir()
    (src_dir / "subdir" / "test2.txt").write_text("Test content 2")
    
    # Test copying
    copy_files(lfs, src_dir.glob("**/*"), src_dir)
    
    # Verify files were copied to LittleFS
    # We can't use exists(), so we'll check if the files are in the buffer
    buffer = lfs.context.buffer
    assert b"Test content" in buffer
    assert b"Test content 2" in buffer

def test_copy_manifest_or_dir(temp_dir, lfs):
    """Test manifest-based file copying."""
    # Create source directory with test files
    src_dir = temp_dir / "src"
    src_dir.mkdir()
    (src_dir / "test1.txt").write_text("Test 1")
    (src_dir / "test2.txt").write_text("Test 2")
    
    # Create manifest file
    manifest = temp_dir / "manifest.txt"
    manifest.write_text("test1.txt\n")
    
    # Test copying with manifest
    copy_manifest_or_dir(lfs, src_dir, manifest)
    
    # Verify only manifest-specified files were copied to LittleFS
    buffer = lfs.context.buffer
    assert b"Test 1" in buffer
    assert b"Test 2" not in buffer

def test_append_to_uf2(temp_dir, sample_uf2_data, lfs):
    """Test appending to UF2 file."""
    # Create source UF2 file
    source_uf2 = temp_dir / "source.uf2"
    source_uf2.write_bytes(sample_uf2_data)
    
    # Create filesystem data to append
    fs_data = lfs.context.buffer
    
    # Test appending
    output_uf2 = temp_dir / "output.uf2"
    append_to_uf2(
        source_uf2,
        fs_data,
        output_uf2,
        fs_start=0x2000,
        fs_overwrite=False,
        sparse=False
    )
    
    # Verify output file (with modified name)
    expected_output = temp_dir / "source-output.uf2"
    assert expected_output.exists()
    output_data = expected_output.read_bytes()
    assert b"Test data" in output_data

def test_main_invalid_args():
    """Test main function with invalid arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose-level", default="INFO")
    parser.add_argument("source_dir", type=Path)
    args = parser.parse_args(["nonexistent_dir"])
    with pytest.raises(FileNotFoundError):
        main(args)

def test_main_missing_source():
    """Test main function with missing source directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose-level", default="INFO")
    parser.add_argument("source_dir", type=Path)
    args = parser.parse_args(["nonexistent_dir"])
    with pytest.raises(FileNotFoundError):
        main(args) 