"""Small, dependency-free readers for common audio containers.

The goal is not to be a complete tag editor.  Sound Isle only needs enough
information to present a useful library: title / artist / album / genre,
duration, basic stream details and (lazily) embedded cover art.

Supported readers: MP3 (ID3v1/ID3v2), FLAC, WAV, Ogg Vorbis, Ogg Opus,
MP4/M4A and raw AAC (duration is best-effort).  Unknown or damaged files
degrade gracefully to filename-derived information.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, List, Optional, Tuple


MAX_COVER_BYTES = 12 * 1024 * 1024
MAX_TAG_BYTES = 24 * 1024 * 1024


@dataclass
class AudioMeta:
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    year: str = ""
    track: str = ""
    duration: Optional[float] = None
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    has_cover: bool = False
    cover: Optional[bytes] = field(default=None, repr=False)
    cover_mime: str = ""


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def _clean(value: str) -> str:
    value = value.replace("\x00", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _first_non_empty(*values: str) -> str:
    for value in values:
        value = _clean(value)
        if value:
            return value
    return ""


def _syncsafe(data: bytes) -> int:
    result = 0
    for byte in data[:4]:
        result = (result << 7) | (byte & 0x7F)
    return result


def _decode_loose(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if encoding == "utf-8-sig" or any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return text
    return raw.decode("latin-1", "replace")


def _decode_id3_text(raw: bytes, encoding: int) -> str:
    if not raw:
        return ""
    if encoding == 1:
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError:
            text = raw.decode("utf-16-le", "replace")
    elif encoding == 2:
        text = raw.decode("utf-16-be", "replace")
    elif encoding == 3:
        text = raw.decode("utf-8", "replace")
    else:
        # ID3 encoding 0 is officially Latin-1, but a generation of Chinese
        # MP3s stored GBK bytes there.  Prefer the reading that produces CJK.
        latin = raw.decode("latin-1", "replace")
        try:
            gbk = raw.decode("gb18030")
            if any("\u4e00" <= ch <= "\u9fff" for ch in gbk) and not any(
                "\u4e00" <= ch <= "\u9fff" for ch in latin
            ):
                text = gbk
            else:
                text = latin
        except UnicodeDecodeError:
            text = latin
    parts = [part for part in text.replace("\x00", "\n").split("\n") if part.strip()]
    return _clean(" / ".join(parts))


def _decode_terminated(raw: bytes, encoding: int) -> Tuple[str, bytes]:
    """Split a NUL-terminated ID3 string, respecting UTF-16 alignment."""
    if encoding in (1, 2):
        step = 2
        for index in range(0, max(0, len(raw) - 1), step):
            if raw[index : index + 2] == b"\x00\x00":
                return raw[:index].decode("utf-16" if encoding == 1 else "utf-16-be", "replace"), raw[index + 2 :]
        return raw.decode("utf-16" if encoding == 1 else "utf-16-be", "replace"), b""
    index = raw.find(b"\x00")
    if index < 0:
        return _decode_id3_text(raw, encoding), b""
    return _decode_id3_text(raw[:index], encoding), raw[index + 1 :]


def _mime_from_bytes(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


def _guess_bitrate(size: int, duration: Optional[float]) -> Optional[int]:
    if not duration or duration <= 0:
        return None
    return max(1, round(size * 8 / duration / 1000))


# ---------------------------------------------------------------------------
# ID3
# ---------------------------------------------------------------------------


_TEXT_FRAMES = {
    "TIT2": "title",
    "TPE1": "artist",
    "TALB": "album",
    "TCON": "genre",
    "TDRC": "year",
    "TYER": "year",
    "TRCK": "track",
    "TT2": "title",
    "TP1": "artist",
    "TAL": "album",
    "TCO": "genre",
    "TYE": "year",
    "TRK": "track",
}

_V22_FRAMES = {
    "TT2": "title",
    "TP1": "artist",
    "TAL": "album",
    "TCO": "genre",
    "TYE": "year",
    "TRK": "track",
}


def _normalise_genre(value: str) -> str:
    value = _clean(value)
    match = re.match(r"^\((\d+)\)\s*(.*)$", value)
    if match:
        return _clean(match.group(2))
    if value.isdigit():
        return ""
    return value


def _parse_apic(data: bytes) -> Tuple[Optional[bytes], str]:
    if not data:
        return None, ""
    encoding = data[0]
    rest = data[1:]
    separator = rest.find(b"\x00")
    if separator < 0:
        return None, ""
    mime = rest[:separator].decode("latin-1", "replace").strip()
    rest = rest[separator + 1 :]
    if len(rest) < 2:
        return None, ""
    rest = rest[1:]  # picture type
    _, rest = _decode_terminated(rest, encoding)
    if not rest:
        return None, ""
    payload = rest[:MAX_COVER_BYTES]
    return payload, mime or _mime_from_bytes(payload)


def _parse_id3_frames(raw: bytes, major: int, flags: int, meta: AudioMeta, want_cover: bool) -> None:
    if flags & 0x80:
        raw = raw.replace(b"\xff\x00", b"\xff")
    position = 0
    # Skip an extended header when present.
    if flags & 0x40 and len(raw) >= 4:
        if major == 4:
            position = min(len(raw), _syncsafe(raw[:4]))
        else:
            position = min(len(raw), 4 + int.from_bytes(raw[:4], "big"))

    frame_header = 6 if major == 2 else 10
    guard = 0
    while position + frame_header <= len(raw) and guard < 10000:
        guard += 1
        if major == 2:
            frame_id = raw[position : position + 3].decode("latin-1", "replace")
            if not re.match(r"^[A-Z0-9]{3}$", frame_id):
                break
            frame_size = int.from_bytes(raw[position + 3 : position + 6], "big")
            body_start = position + 6
        else:
            frame_id = raw[position : position + 4].decode("latin-1", "replace")
            if not re.match(r"^[A-Z0-9]{4}$", frame_id):
                break
            size_bytes = raw[position + 4 : position + 8]
            frame_size = _syncsafe(size_bytes) if major == 4 else int.from_bytes(size_bytes, "big")
            body_start = position + 10
        if frame_size <= 0 or body_start + frame_size > len(raw):
            break
        body = raw[body_start : body_start + frame_size]
        position = body_start + frame_size

        field_name = _TEXT_FRAMES.get(frame_id)
        if field_name and body:
            encoding = body[0]
            value = _decode_id3_text(body[1:], encoding)
            if field_name == "genre":
                value = _normalise_genre(value)
            if value and not getattr(meta, field_name):
                setattr(meta, field_name, value)
        elif frame_id in ("APIC", "PIC"):
            meta.has_cover = True
            if want_cover and meta.cover is None:
                if frame_id == "PIC":
                    picture = body[1:]
                    fmt = picture[:3].decode("latin-1", "replace").lower()
                    rest = picture[3:]
                    payload = rest[rest.find(b"\x00") + 1 :] if b"\x00" in rest else rest
                    if payload:
                        meta.cover = payload[:MAX_COVER_BYTES]
                        meta.cover_mime = _mime_from_bytes(meta.cover)
                else:
                    meta.cover, meta.cover_mime = _parse_apic(body)


def _read_id3v1(handle: BinaryIO, meta: AudioMeta) -> None:
    try:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size < 128:
            return
        handle.seek(-128, os.SEEK_END)
        data = handle.read(128)
    except OSError:
        return
    if not data.startswith(b"TAG"):
        return
    values = {
        "title": data[3:33],
        "artist": data[33:63],
        "album": data[63:93],
        "year": data[93:97],
    }
    for key, raw in values.items():
        if not getattr(meta, key):
            setattr(meta, key, _clean(raw.decode("latin-1", "replace")))
    if data[125] == 0 and data[126] != 0 and not meta.track:
        meta.track = str(data[126])


def _read_mp3(path: Path, want_cover: bool) -> AudioMeta:
    meta = AudioMeta()
    size = path.stat().st_size
    tag_size = 0
    first_frame = 0
    try:
        with open(path, "rb") as handle:
            header = handle.read(10)
            if header[:3] == b"ID3" and len(header) == 10:
                major = header[3]
                flags = header[5]
                tag_size = 10 + _syncsafe(header[6:10])
                if flags & 0x10:
                    tag_size += 10  # footer
                tag_size = min(tag_size, min(size, MAX_TAG_BYTES))
                handle.seek(10)
                raw = handle.read(max(0, tag_size - 10))
                _parse_id3_frames(raw, major, flags, meta, want_cover)
            _read_id3v1(handle, meta)

            handle.seek(tag_size if tag_size < size else 0)
            probe = handle.read(256 * 1024)
            frame_offset = None
            frame_info = None
            for index in range(0, max(0, len(probe) - 4)):
                if probe[index] == 0xFF and (probe[index + 1] & 0xE0) == 0xE0:
                    info = _mp3_frame_info(probe[index : index + 4])
                    if info:
                        frame_offset = index
                        frame_info = info
                        break
            if frame_offset is None or frame_info is None:
                return meta

            first_frame = tag_size + frame_offset
            meta.sample_rate = frame_info["sample_rate"]
            meta.channels = frame_info["channels"]
            bitrate = frame_info["bitrate"]
            duration: Optional[float] = None

            # Xing / Info / VBRI headers carry the exact frame count.
            window_start = max(0, frame_offset - 4)
            window = probe[window_start : window_start + 2048]
            for magic in (b"Xing", b"Info", b"VBRI"):
                idx = window.find(magic)
                if idx < 0:
                    continue
                if magic == b"VBRI":
                    if len(window) >= idx + 18:
                        frames = int.from_bytes(window[idx + 14 : idx + 18], "big")
                        if frames > 0:
                            duration = frames * frame_info["samples"] / frame_info["sample_rate"]
                    break
                if len(window) >= idx + 12:
                    header_flags = int.from_bytes(window[idx + 4 : idx + 8], "big")
                    if header_flags & 0x01:
                        frames = int.from_bytes(window[idx + 8 : idx + 12], "big")
                        if frames > 0:
                            duration = frames * frame_info["samples"] / frame_info["sample_rate"]
                    break

            if not duration and bitrate:
                audio_bytes = max(0, size - first_frame)
                duration = audio_bytes * 8 / (bitrate * 1000)
            meta.duration = round(duration, 3) if duration else None
            meta.bitrate = _guess_bitrate(size, meta.duration) or bitrate
    except (OSError, ValueError, struct.error):
        pass
    return meta


def _mp3_frame_info(header: bytes) -> Optional[Dict[str, int]]:
    if len(header) < 4:
        return None
    b1, b2, b3 = header[1], header[2], header[3]
    version_bits = (b1 >> 3) & 0x03
    layer_bits = (b1 >> 1) & 0x03
    if version_bits == 1 or layer_bits == 0:
        return None
    version = {0: 2.5, 2: 2, 3: 1}[version_bits]
    layer = {3: 1, 2: 2, 1: 3}[layer_bits]
    bitrate_index = (b2 >> 4) & 0x0F
    sample_index = (b2 >> 2) & 0x03
    padding = (b2 >> 1) & 0x01
    if bitrate_index in (0, 15) or sample_index == 3:
        return None

    if version == 1:
        if layer == 1:
            table = [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448]
        elif layer == 2:
            table = [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384]
        else:
            table = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
        sample_base = [44100, 48000, 32000][sample_index]
    else:
        if layer == 1:
            table = [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256]
        else:
            table = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
        sample_base = [44100, 48000, 32000][sample_index] // (2 if version == 2 else 4)

    bitrate = table[bitrate_index]
    sample_rate = sample_base
    samples = 384 if layer == 1 else (1152 if (layer == 2 or version == 1) else 576)
    if layer == 1:
        frame_length = (12 * bitrate * 1000 // sample_rate + padding) * 4
    else:
        frame_length = (samples // 8) * bitrate * 1000 // sample_rate + padding
    channel_mode = (b3 >> 6) & 0x03
    return {
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "channels": 1 if channel_mode == 3 else 2,
        "samples": samples,
        "frame_length": frame_length,
    }


# ---------------------------------------------------------------------------
# WAV
# ---------------------------------------------------------------------------


def _read_wav(path: Path, want_cover: bool) -> AudioMeta:
    meta = AudioMeta()
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            return meta
        byte_rate = 0
        data_size = 0
        info: Dict[str, bytes] = {}
        guard = 0
        while guard < 512:
            guard += 1
            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id = chunk_header[:4]
            chunk_size = int.from_bytes(chunk_header[4:], "little")
            if chunk_size < 0:
                break
            if chunk_id == b"fmt ":
                body = handle.read(min(chunk_size, 64))
                if len(body) >= 16:
                    channels, sample_rate, byte_rate = struct.unpack("<HII", body[2:12])
                    meta.channels = channels or None
                    meta.sample_rate = sample_rate or None
                if chunk_size > len(body):
                    handle.seek(chunk_size - len(body), os.SEEK_CUR)
            elif chunk_id == b"data":
                data_size = chunk_size
                handle.seek(chunk_size, os.SEEK_CUR)
            elif chunk_id == b"LIST":
                body = handle.read(min(chunk_size, 2 * 1024 * 1024))
                if len(body) < chunk_size:
                    handle.seek(chunk_size - len(body), os.SEEK_CUR)
                if body[:4] == b"INFO":
                    pos = 4
                    while pos + 8 <= len(body):
                        sub_id = body[pos : pos + 4].decode("latin-1", "replace")
                        sub_size = int.from_bytes(body[pos + 4 : pos + 8], "little")
                        pos += 8
                        if sub_size > len(body) - pos:
                            break
                        info[sub_id] = body[pos : pos + sub_size].rstrip(b"\x00")
                        pos += sub_size + (sub_size & 1)
            else:
                handle.seek(chunk_size, os.SEEK_CUR)
            if chunk_size & 1:
                handle.seek(1, os.SEEK_CUR)
        if data_size and byte_rate:
            meta.duration = round(data_size / byte_rate, 3)
            meta.bitrate = round(byte_rate * 8 / 1000)
        meta.title = _first_non_empty(_decode_loose(info.get("INAM", b"")), meta.title)
        meta.artist = _first_non_empty(_decode_loose(info.get("IART", b"")), meta.artist)
        meta.album = _first_non_empty(_decode_loose(info.get("IPRD", b"")), meta.album)
        meta.genre = _first_non_empty(_decode_loose(info.get("IGNR", b"")), meta.genre)
        meta.year = _first_non_empty(_decode_loose(info.get("ICRD", b"")), meta.year)
        meta.track = _first_non_empty(_decode_loose(info.get("ITRK", b"")), meta.track)
    return meta


# ---------------------------------------------------------------------------
# FLAC
# ---------------------------------------------------------------------------


def _read_flac(path: Path, want_cover: bool) -> AudioMeta:
    meta = AudioMeta()
    size = path.stat().st_size
    with open(path, "rb") as handle:
        if handle.read(4) != b"fLaC":
            return meta
        last = False
        guard = 0
        while not last and guard < 128:
            guard += 1
            header = handle.read(4)
            if len(header) < 4:
                break
            last = bool(header[0] & 0x80)
            block_type = header[0] & 0x7F
            length = int.from_bytes(header[1:4], "big")
            body_start = handle.tell()
            if block_type == 0 and length >= 34:
                body = handle.read(length)
                packed = int.from_bytes(body[10:18], "big")
                sample_rate = (packed >> 44) & 0xFFFFF
                channels = ((packed >> 41) & 0x07) + 1
                total_samples = packed & ((1 << 36) - 1)
                meta.sample_rate = sample_rate or None
                meta.channels = channels
                if sample_rate and total_samples:
                    meta.duration = round(total_samples / sample_rate, 3)
            elif block_type == 4:
                body = handle.read(min(length, 4 * 1024 * 1024))
                _apply_vorbis_comments(body, meta)
                if length > len(body):
                    handle.seek(length - len(body), os.SEEK_CUR)
            elif block_type == 6:
                meta.has_cover = True
                if want_cover and meta.cover is None and length <= MAX_COVER_BYTES + 1024:
                    body = handle.read(length)
                    cover, mime = _parse_flac_picture(body)
                    if cover:
                        meta.cover = cover
                        meta.cover_mime = mime
                else:
                    handle.seek(length, os.SEEK_CUR)
            else:
                handle.seek(length, os.SEEK_CUR)
            if handle.tell() < body_start + length:
                handle.seek(body_start + length)
        if meta.duration:
            meta.bitrate = _guess_bitrate(size, meta.duration)
    return meta


def _parse_flac_picture(body: bytes) -> Tuple[Optional[bytes], str]:
    try:
        position = 4  # picture type
        mime_len = int.from_bytes(body[position : position + 4], "big")
        position += 4
        mime = body[position : position + mime_len].decode("latin-1", "replace")
        position += mime_len
        desc_len = int.from_bytes(body[position : position + 4], "big")
        position += 4 + desc_len
        position += 16  # width, height, depth, colours
        data_len = int.from_bytes(body[position : position + 4], "big")
        position += 4
        payload = body[position : position + min(data_len, MAX_COVER_BYTES)]
        return payload, mime or _mime_from_bytes(payload)
    except (IndexError, ValueError):
        return None, ""


def _apply_vorbis_comments(body: bytes, meta: AudioMeta) -> None:
    if len(body) < 8:
        return
    position = 0
    vendor_len = int.from_bytes(body[position : position + 4], "little")
    position += 4 + vendor_len
    if position + 4 > len(body):
        return
    count = int.from_bytes(body[position : position + 4], "little")
    position += 4
    tags: Dict[str, str] = {}
    for _ in range(min(count, 512)):
        if position + 4 > len(body):
            break
        item_len = int.from_bytes(body[position : position + 4], "little")
        position += 4
        if item_len > len(body) - position:
            break
        raw = body[position : position + item_len]
        position += item_len
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:
            continue
        if "=" in text:
            key, value = text.split("=", 1)
            tags[key.strip().upper()] = _clean(value)
    field_map = {
        "TITLE": "title",
        "ARTIST": "artist",
        "ALBUM": "album",
        "GENRE": "genre",
        "DATE": "year",
        "YEAR": "year",
        "TRACKNUMBER": "track",
    }
    for key, field_name in field_map.items():
        value = tags.get(key, "")
        if value and not getattr(meta, field_name):
            setattr(meta, field_name, _normalise_genre(value) if field_name == "genre" else value)


# ---------------------------------------------------------------------------
# Ogg Vorbis / Opus
# ---------------------------------------------------------------------------


def _ogg_packets(handle: BinaryIO, wanted: int = 2, limit: int = 2 * 1024 * 1024) -> List[bytes]:
    packets: List[bytes] = []
    current = bytearray()
    consumed = 0
    while len(packets) < wanted and consumed < limit:
        consumed += 27
        header = handle.read(27)
        if len(header) < 27 or header[:4] != b"OggS":
            break
        segment_count = header[26]
        table = handle.read(segment_count)
        consumed += segment_count
        if len(table) < segment_count:
            break
        body_size = sum(table)
        consumed += body_size
        body = handle.read(body_size)
        if len(body) < body_size:
            break
        position = 0
        for segment in table:
            current.extend(body[position : position + segment])
            position += segment
            if segment < 255:
                packets.append(bytes(current))
                current.clear()
                if len(packets) >= wanted:
                    break
    return packets


def _read_ogg(path: Path, want_cover: bool) -> AudioMeta:
    meta = AudioMeta()
    size = path.stat().st_size
    with open(path, "rb") as handle:
        packets = _ogg_packets(handle, wanted=2)
        if not packets:
            return meta
        ident = packets[0]
        sample_rate = None
        pre_skip = 0
        is_opus = ident.startswith(b"OpusHead")
        if is_opus and len(ident) >= 19:
            channels = ident[9]
            pre_skip = int.from_bytes(ident[10:12], "little")
            sample_rate = 48000
        elif ident.startswith(b"\x01vorbis") and len(ident) >= 16:
            channels = ident[11]
            sample_rate = int.from_bytes(ident[12:16], "little")
        else:
            channels = None
        meta.sample_rate = sample_rate
        meta.channels = channels
        if len(packets) > 1:
            comment = packets[1]
            if comment.startswith(b"OpusTags"):
                _apply_ogg_comment_packet(comment[8:], meta)
            elif comment.startswith(b"\x03vorbis"):
                _apply_ogg_comment_packet(comment[7:], meta)

        # The last Ogg page's granule position gives the duration.
        granule = _ogg_last_granule(handle, size)
        if granule and sample_rate:
            frames = granule - pre_skip if is_opus else granule
            if frames > 0:
                meta.duration = round(frames / sample_rate, 3)
                meta.bitrate = _guess_bitrate(size, meta.duration)
    return meta


def _apply_ogg_comment_packet(body: bytes, meta: AudioMeta) -> None:
    _apply_vorbis_comments(body, meta)


def _ogg_last_granule(handle: BinaryIO, size: int) -> int:
    window = min(262144, size)
    if window <= 0:
        return 0
    handle.seek(size - window)
    data = handle.read(window)
    best = 0
    position = 0
    while True:
        index = data.find(b"OggS", position)
        if index < 0:
            break
        if index + 14 <= len(data):
            granule = int.from_bytes(data[index + 6 : index + 14], "little")
            if granule != 0xFFFFFFFFFFFFFFFF:
                best = max(best, granule)
        position = index + 4
    return best


# ---------------------------------------------------------------------------
# MP4 / M4A
# ---------------------------------------------------------------------------


def _mp4_children(handle: BinaryIO, start: int, end: int) -> Iterable[Tuple[str, int, int]]:
    position = start
    guard = 0
    while position + 8 <= end and guard < 10000:
        guard += 1
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            break
        size = int.from_bytes(header[:4], "big")
        kind = header[4:8].decode("latin-1", "replace")
        header_size = 8
        if size == 1:
            extra = handle.read(8)
            if len(extra) < 8:
                break
            size = int.from_bytes(extra, "big")
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            break
        yield kind, position + header_size, position + size
        position += size


def _read_mp4(path: Path, want_cover: bool) -> AudioMeta:
    meta = AudioMeta()
    size = path.stat().st_size
    with open(path, "rb") as handle:
        moov = None
        for kind, start, end in _mp4_children(handle, 0, size):
            if kind == "moov":
                moov = (start, end)
                break
            if kind == "mdat":
                continue
        if not moov:
            return meta
        for kind, start, end in _mp4_children(handle, moov[0], moov[1]):
            if kind == "mvhd":
                _parse_mvhd(handle, start, min(end, start + 256), meta)
        for kind, start, end in _mp4_children(handle, moov[0], moov[1]):
            if kind == "udta":
                _find_mp4_meta(handle, start, end, meta, want_cover)
        if meta.duration:
            meta.bitrate = _guess_bitrate(size, meta.duration)
    return meta


def _parse_mvhd(handle: BinaryIO, start: int, end: int, meta: AudioMeta) -> None:
    handle.seek(start)
    body = handle.read(max(0, min(end - start, 128)))
    if len(body) < 20:
        return
    version = body[0]
    try:
        if version == 1 and len(body) >= 32:
            timescale = int.from_bytes(body[20:24], "big")
            duration = int.from_bytes(body[24:32], "big")
        else:
            timescale = int.from_bytes(body[12:16], "big")
            duration = int.from_bytes(body[16:20], "big")
        if timescale and duration:
            meta.duration = round(duration / timescale, 3)
    except (IndexError, ValueError):
        return


def _find_mp4_meta(handle: BinaryIO, start: int, end: int, meta: AudioMeta, want_cover: bool) -> None:
    for kind, child_start, child_end in _mp4_children(handle, start, end):
        if kind == "meta":
            # meta is a FullBox: skip version/flags before its children.
            _read_ilst(handle, child_start + 4, child_end, meta, want_cover)
        else:
            _find_mp4_meta(handle, child_start, child_end, meta, want_cover)


def _read_ilst(handle: BinaryIO, start: int, end: int, meta: AudioMeta, want_cover: bool) -> None:
    for kind, child_start, child_end in _mp4_children(handle, start, end):
        data_atoms = list(_mp4_children(handle, child_start, child_end))
        for data_kind, data_start, data_end in data_atoms:
            if data_kind != "data":
                continue
            length = min(data_end - data_start, MAX_COVER_BYTES + 8)
            handle.seek(data_start)
            payload = handle.read(length)
            if len(payload) < 8:
                continue
            data_type = int.from_bytes(payload[0:4], "big") & 0xFFFFFF
            content = payload[8:]
            if kind in ("©nam", "©ART", "aART", "©alb", "©gen", "©day", "©wrt", "desc"):
                field_map = {
                    "©nam": "title",
                    "©ART": "artist",
                    "aART": "artist",
                    "©alb": "album",
                    "©gen": "genre",
                    "©day": "year",
                }
                field_name = field_map.get(kind)
                if field_name and content:
                    value = _decode_loose(content).strip("\x00")
                    if value and not getattr(meta, field_name):
                        setattr(meta, field_name, _clean(value))
            elif kind == "trkn" and len(content) >= 4:
                number = int.from_bytes(content[2:4], "big")
                if number and not meta.track:
                    meta.track = str(number)
            elif kind == "covr":
                meta.has_cover = True
                if want_cover and meta.cover is None and content:
                    meta.cover = content[:MAX_COVER_BYTES]
                    if data_type == 14 or meta.cover.startswith(b"\x89PNG"):
                        meta.cover_mime = "image/png"
                    else:
                        meta.cover_mime = _mime_from_bytes(meta.cover)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def read_audio(path: Path, want_cover: bool = False) -> AudioMeta:
    """Read metadata without ever raising for a bad/unknown file."""
    suffix = path.suffix.lower()
    meta = AudioMeta()
    try:
        if suffix == ".mp3":
            meta = _read_mp3(path, want_cover)
        elif suffix == ".flac":
            meta = _read_flac(path, want_cover)
        elif suffix == ".wav":
            meta = _read_wav(path, want_cover)
        elif suffix in (".ogg", ".oga", ".opus"):
            meta = _read_ogg(path, want_cover)
        elif suffix in (".m4a", ".m4b", ".mp4", ".aac"):
            meta = _read_mp4(path, want_cover)
        elif suffix == ".aiff" or suffix == ".aif":
            meta = _read_aiff(path)
    except (OSError, ValueError, IndexError, struct.error, MemoryError):
        meta = AudioMeta()
    if not meta.has_cover and meta.cover:
        meta.has_cover = True
    return meta


def read_cover(path: Path) -> Tuple[str, Optional[bytes]]:
    """Return (mime, bytes) for an embedded cover, if one can be found."""
    meta = read_audio(path, want_cover=True)
    if meta.cover:
        return meta.cover_mime or _mime_from_bytes(meta.cover), meta.cover
    return "", None


def _read_aiff(path: Path) -> AudioMeta:
    """Minimal AIFF duration reader (AIFF/AIFC)."""
    meta = AudioMeta()
    try:
        with open(path, "rb") as handle:
            header = handle.read(12)
            if len(header) < 12 or header[:4] != b"FORM" or header[8:12] not in (b"AIFF", b"AIFC"):
                return meta
            while True:
                chunk_header = handle.read(8)
                if len(chunk_header) < 8:
                    break
                kind = chunk_header[:4]
                length = int.from_bytes(chunk_header[4:], "big")
                if kind == b"COMM":
                    body = handle.read(min(length, 64))
                    if len(body) >= 18:
                        channels = int.from_bytes(body[0:2], "big")
                        frames = int.from_bytes(body[2:6], "big")
                        rate = _extended_float(body[8:18])
                        meta.channels = channels or None
                        meta.sample_rate = int(rate) if rate else None
                        if rate and frames:
                            meta.duration = round(frames / rate, 3)
                    if length > len(body):
                        handle.seek(length - len(body), os.SEEK_CUR)
                else:
                    handle.seek(length, os.SEEK_CUR)
                if length & 1:
                    handle.seek(1, os.SEEK_CUR)
    except (OSError, ValueError, IndexError):
        pass
    return meta


def _extended_float(data: bytes) -> float:
    if len(data) < 10:
        return 0.0
    exponent = int.from_bytes(data[0:2], "big") & 0x7FFF
    mantissa = int.from_bytes(data[2:10], "big")
    if exponent == 0 and mantissa == 0:
        return 0.0
    sign = -1 if data[0] & 0x80 else 1
    return sign * mantissa * (2.0 ** (exponent - 16383 - 63))


# ---------------------------------------------------------------------------
# Filename fallbacks
# ---------------------------------------------------------------------------


_LEADING_TRACK_RE = re.compile(r"^\s*\d{1,3}\s*[._\-]\s+")


def guess_from_filename(filename: str) -> Tuple[str, str]:
    """Return (title, artist) guessed from a filename stem."""
    stem = Path(filename).stem
    stem = _LEADING_TRACK_RE.sub("", stem).strip()
    title = stem
    artist = ""
    for separator in (" - ", " – ", " — ", "_-_", "_–_"):
        if separator in stem:
            left, right = stem.split(separator, 1)
            if left.strip() and right.strip():
                artist = left.strip()
                title = right.strip()
            break
    if not title:
        title = stem
    return _clean(title), _clean(artist)
