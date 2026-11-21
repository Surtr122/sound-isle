"""Core tests for Sound & Form.

Run from the project root:

    python -m unittest discover -s tests -v

The tests only touch temporary folders.  They never read or modify the
music folders used during development.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundisle.classify import (
    classify_animation_subcategory,
    classify_asset,
    classify_sfx_subcategory,
    classify_track,
)
from soundisle.library import Library, LibraryError
from soundisle.metadata import AudioMeta, guess_from_filename, read_audio
from soundisle.probe import AssetProbe
from soundisle.motion import load_bvh, load_fbx, load_gltf
from soundisle.rename import (
    RenameError,
    apply_plan,
    build_plan,
    natural_key,
    validate_options,
)
from soundisle.server import create_server
from soundisle.workspace import Workspace


def make_wav(path: Path, seconds: float = 0.25, sample_rate: int = 8000) -> None:
    frames = max(1, int(seconds * sample_rate))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)


def make_glb(path: Path) -> None:
    """Write a minimal skinned GLB with one two-frame rotation channel."""
    times = struct.pack("<2f", 0.0, 1.0)
    # Quaternions are stored xyzw: identity then ~90 degrees around Z.
    rotations = struct.pack("<8f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.7071068, 0.7071068)
    binary = times + rotations
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(times)},
            {"buffer": 0, "byteOffset": len(times), "byteLength": len(rotations)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC4"},
        ],
        "nodes": [
            {"name": "Hips", "children": [1]},
            {"name": "Spine", "translation": [0.0, 1.0, 0.0]},
        ],
        "skins": [{"joints": [0, 1]}],
        "animations": [
            {
                "name": "走路",
                "samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}],
            }
        ],
    }
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    payload = (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
    path.write_bytes(payload)


def make_bvh(path: Path, frames: int = 2) -> None:
    rows = [
        "HIERARCHY",
        "ROOT Hips",
        "{",
        "  OFFSET 0 0 0",
        "  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation",
        "  JOINT Spine",
        "  {",
        "    OFFSET 0 10 0",
        "    CHANNELS 3 Zrotation Xrotation Yrotation",
        "    End Site",
        "    {",
        "      OFFSET 0 8 0",
        "    }",
        "  }",
        "}",
        "MOTION",
        f"Frames: {frames}",
        "Frame Time: 0.0333333",
    ]
    for index in range(frames):
        rows.append(f"0 0 0 0 0 {index * 3} 0 {index * 4} 0")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def make_ascii_fbx(path: Path) -> None:
    """Write a tiny ASCII FBX 7.4 file with two bones and one rotation curve."""
    text = """; FBX 7.4.0 project file
FBXHeaderExtension: {
    FBXVersion: 7400
}
Objects: {
    Model: 1, "Model::Root", "LimbNode" {
        Properties70: {
            P: "Lcl Translation", "Lcl Translation", "", "A",0,0,0
        }
    }
    Model: 2, "Model::Spine", "LimbNode" {
        Properties70: {
            P: "Lcl Translation", "Lcl Translation", "", "A",0,10,0
        }
    }
    NodeAttribute: 3, "NodeAttribute::", "LimbNode" {
        Properties70: {
            P: "Size", "double", "Number", "", 1.0
        }
    }
    AnimationCurveNode: 10, "AnimCurveNode::T", "" {
    }
    AnimationCurve: 20, "AnimCurve::", "" {
        KeyTime: *2 {
            a: 0, 46186158000
        }
        KeyValueFloat: *2 {
            a: 0, 45
        }
    }
}
Connections: {
    C: "OO", 1, 0
    C: "OO", 2, 1
    C: "OP", 10, 2, "Lcl Rotation"
    C: "OP", 20, 10, "d|X"
}
"""
    path.write_text(text, encoding="utf-8")



class RenameEngineTests(unittest.TestCase):
    def test_natural_key_orders_numbers(self) -> None:
        values = ["第10章.wav", "第2章.wav", "第1章.wav"]
        self.assertEqual(sorted(values, key=natural_key), ["第1章.wav", "第2章.wav", "第10章.wav"])

    def test_validate_options_rejects_bad_names(self) -> None:
        with self.assertRaises(RenameError):
            validate_options("", 1, 2, " ")
        with self.assertRaises(RenameError):
            validate_options("a/b", 1, 2, " ")
        with self.assertRaises(RenameError):
            validate_options("ok", -1, 2, " ")
        with self.assertRaises(RenameError):
            validate_options("ok", 1, 7, " ")

    def test_plan_and_apply_keep_extension_and_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "a.wav"
            second = root / "b.wav"
            make_wav(first)
            make_wav(second)
            options = validate_options("海边录音", 1, 2, " ")
            plan = build_plan(
                [
                    {"id": "a", "rel_path": "a.wav", "path": str(first), "filename": first.name},
                    {"id": "b", "rel_path": "b.wav", "path": str(second), "filename": second.name},
                ],
                options,
            )
            self.assertTrue(plan["ok"])
            self.assertEqual([item["new_name"] for item in plan["items"]], ["海边录音 01.wav", "海边录音 02.wav"])
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()

            result = apply_plan(plan)
            self.assertEqual(result["renamed"], 2)
            self.assertTrue((root / "海边录音 01.wav").is_file())
            self.assertTrue((root / "海边录音 02.wav").is_file())
            self.assertEqual((root / "海边录音 01.wav").read_bytes(), first_bytes)
            self.assertEqual((root / "海边录音 02.wav").read_bytes(), second_bytes)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertEqual(result["mapping"][0]["old_name"], "a.wav")
            self.assertEqual(result["mapping"][0]["new_name"], "海边录音 01.wav")

    def test_existing_target_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "a.wav"
            occupied = root / "已有 01.wav"
            make_wav(source)
            make_wav(occupied)
            plan = build_plan(
                [{"id": "a", "rel_path": "a.wav", "path": str(source), "filename": source.name}],
                validate_options("已有", 1, 2, " "),
            )
            self.assertFalse(plan["ok"])
            self.assertEqual(plan["conflicts"], 1)
            self.assertIn("已有同名文件", plan["items"][0]["error"])

    def test_swap_uses_two_phase_rename(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            a = root / "一.wav"
            b = root / "二.wav"
            make_wav(a)
            make_wav(b)
            # Build a plan that maps 一.wav -> 二 01.wav, 二.wav -> 一 02.wav.
            # This is not a literal swap but exercises two-phase temp names.
            plan = build_plan(
                [
                    {"id": "a", "rel_path": "一.wav", "path": str(a), "filename": a.name},
                    {"id": "b", "rel_path": "二.wav", "path": str(b), "filename": b.name},
                ],
                validate_options("交换", 1, 2, "-"),
            )
            self.assertTrue(plan["ok"])
            apply_plan(plan)
            self.assertTrue((root / "交换-01.wav").is_file())
            self.assertTrue((root / "交换-02.wav").is_file())


class MetadataAndClassifierTests(unittest.TestCase):
    def test_wav_duration_and_stream_info(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sample.wav"
            make_wav(path, seconds=0.5, sample_rate=8000)
            meta = read_audio(path)
            self.assertAlmostEqual(meta.duration or 0, 0.5, places=2)
            self.assertEqual(meta.sample_rate, 8000)
            self.assertEqual(meta.channels, 1)

    def test_filename_guess(self) -> None:
        self.assertEqual(guess_from_filename("周杰伦 - 晴天.mp3"), ("晴天", "周杰伦"))
        self.assertEqual(guess_from_filename("无标题.mp3")[0], "无标题")

    def test_short_audio_is_sfx(self) -> None:
        meta = AudioMeta(duration=3.2)
        result = classify_track("素材/点击.wav", meta)
        self.assertEqual(result["key"], "sfx")
        self.assertGreaterEqual(result["confidence"], 0.9)

    def test_chapter_name_is_audiobook(self) -> None:
        meta = AudioMeta(duration=1800)
        result = classify_track("有声书/第03章 出发.mp3", meta)
        self.assertEqual(result["key"], "audiobook")

    def test_instrumental_hint(self) -> None:
        meta = AudioMeta(duration=240, genre="OST")
        result = classify_track("音乐/钢琴伴奏.wav", meta)
        self.assertEqual(result["key"], "instrumental")

    def test_sfx_subcategory_keywords(self) -> None:
        meta = AudioMeta(duration=2.0)
        foot = classify_track("音效/脚步 01.wav", meta)
        self.assertEqual(foot["key"], "sfx")
        self.assertEqual(foot["subcategory"]["key"], "footstep")
        sigh = classify_sfx_subcategory("人声/叹息 02.wav", meta)
        self.assertEqual(sigh["key"], "sigh")
        attack = classify_sfx_subcategory("战斗/攻击 03.wav", meta)
        self.assertEqual(attack["key"], "attack")
        fallback = classify_sfx_subcategory("未知短音.wav", meta)
        self.assertEqual(fallback["key"], "other")

    def test_animation_subcategory_keywords(self) -> None:
        self.assertEqual(classify_animation_subcategory("动作/走路循环.bvh")["key"], "walk")
        self.assertEqual(classify_animation_subcategory("动作/run_forward.fbx")["key"], "run")
        self.assertEqual(classify_animation_subcategory("动作/受击.bvh")["key"], "hit")
        self.assertEqual(classify_animation_subcategory("动作/未知.bvh")["key"], "other")

    def test_fbx_action_names_are_animation(self) -> None:
        probe = AssetProbe(format="FBX", note="test")
        names = (
            "Dropping.fbx",
            "Jog Forward.fbx",
            "Left Turn.fbx",
            "Looking Through Files Low.fbx",
            "Reaching Out.fbx",
            "Standing Torch Light Torch.fbx",
            "Throw Object.fbx",
            "Unarmed Grab Torch From Floor.fbx",
        )
        for name in names:
            with self.subTest(name=name):
                result = classify_asset(f"动作库/{name}", probe)
                self.assertEqual(result["key"], "animation")


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._data = tempfile.TemporaryDirectory()
        self._library = tempfile.TemporaryDirectory()
        self.addCleanup(self._data.cleanup)
        self.addCleanup(self._library.cleanup)
        self._old_env = os.environ.get("SOUNDISLE_DATA_DIR")
        os.environ["SOUNDISLE_DATA_DIR"] = self._data.name
        self.root = Path(self._library.name)
        (self.root / "nested").mkdir()
        make_wav(self.root / "01.wav")
        make_wav(self.root / "02.wav")
        make_wav(self.root / "nested" / "03.wav")
        self.library = Library(self.root)

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("SOUNDISLE_DATA_DIR", None)
        else:
            os.environ["SOUNDISLE_DATA_DIR"] = self._old_env

    def test_snapshot_has_categories_and_relative_paths(self) -> None:
        snapshot = self.library.snapshot()
        self.assertEqual(snapshot["stats"]["total"], 3)
        self.assertEqual(snapshot["stats"]["audio"], 3)
        self.assertEqual(snapshot["stats"]["assets"], 0)
        self.assertEqual(len(snapshot["categories"]), 15)
        self.assertEqual(sum(1 for item in snapshot["categories"] if item["domain"] == "audio"), 7)
        self.assertEqual(sum(1 for item in snapshot["categories"] if item["domain"] == "asset"), 8)
        self.assertEqual({track["rel_path"] for track in snapshot["tracks"]}, {"01.wav", "02.wav", "nested/03.wav"})
        self.assertTrue(all(track["kind"] == "audio" for track in snapshot["tracks"]))
        self.assertTrue(all(track["stream_url"].startswith("/api/stream/") for track in snapshot["tracks"]))

    def test_tags_and_favorites_are_persisted(self) -> None:
        track = self.library.snapshot()["tracks"][0]
        self.library.add_tags([track["id"]], ["夜晚", "测试"])
        self.library.set_favorite([track["id"]], True)
        fresh = Library(self.root).snapshot()
        row = next(item for item in fresh["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["tags"], ["夜晚", "测试"])
        self.assertTrue(row["favorite"])
        self.assertEqual(fresh["stats"]["tagged"], 1)
        self.assertEqual(fresh["stats"]["favorites"], 1)

    def test_metadata_export_and_import(self) -> None:
        track = self.library.snapshot()["tracks"][0]
        self.library.set_tags(track["id"], ["夜晚", "备份"])
        self.library.set_favorite([track["id"]], True)
        self.library.set_memberships([track["id"]], ["sfx", "instrumental"])
        self.library.set_subcategory([track["id"]], "footstep")
        metadata = self.library.export_metadata()
        self.assertEqual(len(metadata["tracks"]), 3)

        self.library.set_tags(track["id"], [])
        self.library.set_favorite([track["id"]], False)
        self.library.set_memberships([track["id"]], ["song"])
        result = self.library.import_metadata(metadata)
        self.assertEqual(result["imported"], 3)
        self.assertEqual(result["skipped"], 0)
        row = next(item for item in result["library"]["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["tags"], ["夜晚", "备份"])
        self.assertTrue(row["favorite"])
        self.assertEqual([item["key"] for item in row["categories"]], ["sfx", "instrumental"])
        self.assertEqual(row["category"]["subcategory"]["key"], "footstep")

    def test_missing_and_duplicate_files_are_detected(self) -> None:
        (self.root / "copy.wav").write_bytes((self.root / "01.wav").read_bytes())
        self.library.rescan()
        snapshot = self.library.snapshot()
        self.assertTrue(snapshot["duplicates"])
        self.assertGreaterEqual(len(snapshot["duplicates"][0]["tracks"]), 4)

        (self.root / "02.wav").unlink()
        self.library.rescan()
        missing = self.library.snapshot()["missing"]
        self.assertEqual([item["rel_path"] for item in missing], ["02.wav"])
        self.library.dismiss_missing(["02.wav"])
        self.assertFalse(self.library.snapshot()["missing"])

    def test_rename_migrates_tags_and_favorites(self) -> None:
        track = self.library.snapshot()["tracks"][0]
        self.library.add_tags([track["id"]], ["保留"])
        self.library.set_favorite([track["id"]], True)
        result = self.library.rename([track["id"]], "重命名测试", 1, 2, " ")
        self.assertTrue(result["ok"])
        new_id = result["plan"]["mapping"][0]["new_id"]
        fresh = self.library.snapshot()
        renamed = next(item for item in fresh["tracks"] if item["id"] == new_id)
        self.assertEqual(renamed["filename"], "重命名测试 01.wav")
        self.assertEqual(renamed["tags"], ["保留"])
        self.assertTrue(renamed["favorite"])
        self.assertTrue((self.root / "重命名测试 01.wav").is_file())
        self.assertFalse((self.root / "01.wav").exists())

    def test_preview_conflict_does_not_touch_disk(self) -> None:
        target = self.root / "保留 01.wav"
        make_wav(target)
        self.library.rescan()
        track = next(item for item in self.library.snapshot()["tracks"] if item["filename"] == "01.wav")
        plan = self.library.preview_rename([track["id"]], "保留", 1, 2, " ")
        self.assertFalse(plan["ok"])
        self.assertTrue((self.root / "01.wav").is_file())
        self.assertTrue(target.is_file())

    def test_animation_subcategory_can_be_overridden(self) -> None:
        action_dir = self.root / "动作"
        action_dir.mkdir()
        make_bvh(action_dir / "走路循环.bvh", frames=2)
        self.library.rescan()
        track = next(item for item in self.library.snapshot()["tracks"] if item["filename"] == "走路循环.bvh")
        self.assertEqual(track["category"]["key"], "animation")
        self.assertEqual(track["category"]["subcategory"]["key"], "walk")
        self.library.set_subcategory([track["id"]], "run")
        row = next(item for item in self.library.snapshot()["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["subcategory"]["key"], "run")
        self.library.set_subcategory([track["id"]], "auto")
        row = next(item for item in self.library.snapshot()["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["subcategory"]["key"], "walk")

    def test_memberships_and_custom_subcategory(self) -> None:
        track = self.library.snapshot()["tracks"][0]
        child = self.library.create_category("脚步子类", "#4D7C67", parent="sfx")
        self.assertEqual(child["parent"], "sfx")

        snapshot = self.library.set_memberships([track["id"]], ["sfx", child["key"]])
        row = next(item for item in snapshot["tracks"] if item["id"] == track["id"])
        keys = [item["key"] for item in row["categories"]]
        self.assertIn("sfx", keys)
        self.assertIn(child["key"], keys)

        snapshot = self.library.remove_from_category([track["id"]], child["key"])
        row = next(item for item in snapshot["tracks"] if item["id"] == track["id"])
        keys = [item["key"] for item in row["categories"]]
        self.assertIn("sfx", keys)
        self.assertNotIn(child["key"], keys)

        snapshot = self.library.remove_from_category([track["id"]], "sfx")
        row = next(item for item in snapshot["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["key"], "other")

    def test_custom_category_and_sfx_subcategory_are_persisted(self) -> None:
        track = self.library.snapshot()["tracks"][0]
        self.assertEqual(track["category"]["key"], "sfx")
        self.library.set_subcategory([track["id"]], "attack")
        row = next(item for item in self.library.snapshot()["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["subcategory"]["key"], "attack")

        custom = self.library.create_category("战斗音效", "#C85A3A")
        snapshot = self.library.set_category([track["id"]], custom["key"])
        self.assertEqual(len(snapshot["categories"]), 16)
        row = next(item for item in snapshot["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["key"], custom["key"])
        self.assertEqual(row["category"]["domain"], "custom")

        fresh = Library(self.root).snapshot()
        row = next(item for item in fresh["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["key"], custom["key"])
        self.assertEqual(fresh["stats"]["total"], 3)

        restored = self.library.set_category([track["id"]], "auto")
        row = next(item for item in restored["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["category"]["key"], "sfx")


class MixedLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._data = tempfile.TemporaryDirectory()
        self._library = tempfile.TemporaryDirectory()
        self.addCleanup(self._data.cleanup)
        self.addCleanup(self._library.cleanup)
        self._old_env = os.environ.get("SOUNDISLE_DATA_DIR")
        os.environ["SOUNDISLE_DATA_DIR"] = self._data.name
        self.root = Path(self._library.name)
        (self.root / "声音").mkdir()
        make_wav(self.root / "声音" / "主题.wav")
        (self.root / "模型").mkdir()
        (self.root / "模型" / "箱子.obj").write_text(
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
            encoding="utf-8",
        )
        (self.root / "贴图").mkdir()
        (self.root / "贴图" / "albedo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        self.library = Library(self.root)

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("SOUNDISLE_DATA_DIR", None)
        else:
            os.environ["SOUNDISLE_DATA_DIR"] = self._old_env

    def test_mixed_snapshot_and_inspect(self) -> None:
        snapshot = self.library.snapshot()
        self.assertEqual(snapshot["stats"]["total"], 3)
        self.assertEqual(snapshot["stats"]["audio"], 1)
        self.assertEqual(snapshot["stats"]["assets"], 2)
        self.assertEqual(snapshot["stats"]["models"], 1)
        self.assertEqual(snapshot["stats"]["textures"], 1)
        rows = {track["rel_path"]: track for track in snapshot["tracks"]}
        self.assertEqual(rows["声音/主题.wav"]["kind"], "audio")
        self.assertTrue(rows["声音/主题.wav"]["stream_url"].startswith("/api/stream/"))
        self.assertEqual(rows["模型/箱子.obj"]["kind"], "asset")
        self.assertEqual(rows["模型/箱子.obj"]["category"]["key"], "model")
        self.assertEqual(rows["模型/箱子.obj"]["stream_url"], "")
        self.assertTrue(rows["模型/箱子.obj"]["inspect_url"].startswith("/api/inspect/"))
        self.assertEqual(rows["贴图/albedo.png"]["category"]["key"], "texture")
        self.assertTrue(rows["贴图/albedo.png"]["thumb_url"].startswith("/api/thumb/"))
        detail = self.library.inspect(rows["模型/箱子.obj"]["id"])
        self.assertEqual(detail["format"], "OBJ")
        self.assertTrue(Path(detail["absolute_path"]).is_file())
        self.assertIsNone(self.library.stream_path(rows["模型/箱子.obj"]["id"]))


class MotionPreviewTests(unittest.TestCase):
    def test_bvh_preview_has_joints_and_frames(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "idle.bvh"
            make_bvh(path, frames=3)
            motion = load_bvh(path)
            self.assertEqual(motion["kind"], "bvh")
            self.assertGreaterEqual(len(motion["joints"]), 3)
            self.assertEqual(motion["frame_count"], 3)
            self.assertEqual(len(motion["frames"]), 3)
            self.assertAlmostEqual(motion["fps"], 30.0, places=1)
            self.assertTrue(motion["edges"])

    def test_glb_animation_preview(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "walk.glb"
            make_glb(path)
            motion = load_gltf(path)
            self.assertIsNotNone(motion)
            self.assertEqual(motion["kind"], "gltf")
            self.assertEqual(motion["format"], "GLB")
            self.assertEqual(motion["frame_count"], 2)
            self.assertEqual(len(motion["frames"]), 2)
            self.assertEqual(len(motion["joints"]), 2)
            self.assertEqual(motion["animation_name"], "走路")
            self.assertTrue(motion["edges"])

    def test_ascii_fbx_animation_preview(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "spin.fbx"
            make_ascii_fbx(path)
            motion = load_fbx(path)
            self.assertIsNotNone(motion)
            self.assertEqual(motion["kind"], "fbx")
            self.assertEqual(motion["frame_count"], 31)
            self.assertEqual(len(motion["joints"]), 2)
            self.assertEqual(len(motion["frames"]), 31)
            self.assertAlmostEqual(motion["fps"], 30.0, places=1)
            self.assertTrue(motion["edges"])


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._data = tempfile.TemporaryDirectory()
        self._a = tempfile.TemporaryDirectory()
        self._b = tempfile.TemporaryDirectory()
        self.addCleanup(self._data.cleanup)
        self.addCleanup(self._a.cleanup)
        self.addCleanup(self._b.cleanup)
        self._old_env = os.environ.get("SOUNDANDFORM_DATA_DIR")
        os.environ["SOUNDANDFORM_DATA_DIR"] = self._data.name
        self.audio_root = Path(self._a.name) / "声音"
        self.motion_root = Path(self._b.name) / "动作"
        self.audio_root.mkdir()
        self.motion_root.mkdir()
        make_wav(self.audio_root / "01.wav")
        make_bvh(self.motion_root / "走路.bvh", frames=3)
        self.workspace = Workspace([self.audio_root, self.motion_root])

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("SOUNDANDFORM_DATA_DIR", None)
        else:
            os.environ["SOUNDANDFORM_DATA_DIR"] = self._old_env

    def test_merged_snapshot_and_tags(self) -> None:
        snapshot = self.workspace.snapshot()
        self.assertEqual(snapshot["stats"]["total"], 2)
        self.assertEqual(len(snapshot["sources"]), 2)
        self.assertEqual({track["source_name"] for track in snapshot["tracks"]}, {"声音", "动作"})
        self.assertTrue(all("-" in track["id"] for track in snapshot["tracks"]))
        ids = [track["id"] for track in snapshot["tracks"]]
        updated = self.workspace.add_tags(ids, ["共享"])
        self.assertEqual(updated["stats"]["tagged"], 2)
        self.assertTrue(all("共享" in track["tags"] for track in updated["tracks"]))

    def test_cross_source_rename_keeps_bytes_and_extension(self) -> None:
        snapshot = self.workspace.snapshot()
        audio = next(track for track in snapshot["tracks"] if track["kind"] == "audio")
        motion = next(track for track in snapshot["tracks"] if track["kind"] == "asset")
        before = (self.audio_root / "01.wav").read_bytes()
        plan = self.workspace.preview_rename([audio["id"], motion["id"]], "合并", 1, 2, "-")
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["total"], 2)
        result = self.workspace.rename([audio["id"], motion["id"]], "合并", 1, 2, "-")
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.audio_root / "合并-01.wav").is_file())
        self.assertTrue((self.motion_root / "合并-02.bvh").is_file())
        self.assertEqual((self.audio_root / "合并-01.wav").read_bytes(), before)
        self.assertEqual((self.motion_root / "合并-02.bvh").suffix, ".bvh")

    def test_rescan_single_source(self) -> None:
        make_wav(self.audio_root / "02.wav")
        source = next(item for item in self.workspace.sources if item["name"] == "声音")
        snapshot = self.workspace.rescan(source["id"])
        self.assertEqual(snapshot["stats"]["total"], 3)
        self.assertEqual(sum(1 for track in snapshot["tracks"] if track["kind"] == "audio"), 2)
        with self.assertRaises(LibraryError):
            self.workspace.rescan("missing-source")

    def test_add_and_remove_source(self) -> None:
        third = tempfile.TemporaryDirectory()
        self.addCleanup(third.cleanup)
        make_wav(Path(third.name) / "03.wav")
        self.workspace.add_source(third.name)
        self.assertEqual(self.workspace.snapshot()["stats"]["total"], 3)
        target = next(source for source in self.workspace.sources if source["path"] == str(Path(third.name).resolve()))
        self.workspace.remove_source(target["id"])
        self.assertEqual(self.workspace.snapshot()["stats"]["total"], 2)



class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._data = tempfile.TemporaryDirectory()
        self._library = tempfile.TemporaryDirectory()
        self.addCleanup(self._data.cleanup)
        self.addCleanup(self._library.cleanup)
        self._old_env = os.environ.get("SOUNDISLE_DATA_DIR")
        os.environ["SOUNDISLE_DATA_DIR"] = self._data.name
        self.root = Path(self._library.name)
        make_wav(self.root / "one.wav")
        (self.root / "动作").mkdir()
        make_bvh(self.root / "动作" / "idle.bvh")
        (self.root / "model.obj").write_text(
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
            encoding="utf-8",
        )
        (self.root / "thumb.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        self.server, self.state = create_server(str(self.root), port=0, quiet=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self._old_env is None:
            os.environ.pop("SOUNDISLE_DATA_DIR", None)
        else:
            os.environ["SOUNDISLE_DATA_DIR"] = self._old_env

    def _get(self, path: str, headers: dict | None = None):
        request = urllib.request.Request(self.base + path, headers=headers or {})
        return urllib.request.urlopen(request, timeout=5)

    def _post(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(request, timeout=5)

    def test_state_and_static_page(self) -> None:
        with self._get("/api/state") as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["library"]["stats"]["total"], 4)
        self.assertEqual(payload["library"]["stats"]["audio"], 1)
        self.assertEqual(payload["library"]["stats"]["assets"], 3)
        self.assertEqual(payload["app"]["name"], "声形")
        with self._get("/") as response:
            html = response.read().decode("utf-8")
        self.assertIn("声形", html)
        self.assertIn("Sound &amp; Form", html)

    def test_tags_favorites_and_rename(self) -> None:
        snapshot = self.state.library.snapshot()
        track = next(item for item in snapshot["tracks"] if item["kind"] == "audio")
        with self._post("/api/tags/add", {"ids": [track["id"]], "tags": ["测试"]}) as response:
            payload = json.loads(response.read().decode("utf-8"))
        row = next(item for item in payload["library"]["tracks"] if item["id"] == track["id"])
        self.assertEqual(row["tags"], ["测试"])

        with self._post("/api/favorites", {"ids": [track["id"]], "favorite": True}) as response:
            payload = json.loads(response.read().decode("utf-8"))
        row = next(item for item in payload["library"]["tracks"] if item["id"] == track["id"])
        self.assertTrue(row["favorite"])

        with self._post(
            "/api/rename/preview",
            {"ids": [track["id"]], "name": "服务测试", "start": 1, "digits": 2, "separator": " "},
        ) as response:
            plan = json.loads(response.read().decode("utf-8"))["plan"]
        self.assertTrue(plan["ok"])

        with self._post(
            "/api/rename/apply",
            {"ids": [track["id"]], "name": "服务测试", "start": 1, "digits": 2, "separator": " "},
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["plan"]["renamed"], 1)
        self.assertTrue((self.root / "服务测试 01.wav").is_file())
        renamed = next(item for item in result["library"]["tracks"] if item["filename"] == "服务测试 01.wav")
        self.assertTrue(renamed["favorite"])
        self.assertEqual(renamed["tags"], ["测试"])

    def test_asset_inspect_and_thumb(self) -> None:
        snapshot = self.state.library.snapshot()
        model = next(item for item in snapshot["tracks"] if item["filename"] == "model.obj")
        with self._get(f"/api/inspect/{model['id']}") as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["asset"]["category"]["key"], "model")
        self.assertTrue(Path(payload["asset"]["absolute_path"]).is_file())

        texture = next(item for item in snapshot["tracks"] if item["filename"] == "thumb.png")
        self.assertTrue(texture["thumb_url"].startswith("/api/thumb/"))
        with self._get(texture["thumb_url"]) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertTrue(response.read().startswith(b"\x89PNG"))

    def test_taxonomy_and_motion_endpoints(self) -> None:
        snapshot = self.state.library.snapshot()
        audio = next(item for item in snapshot["tracks"] if item["kind"] == "audio")
        bvh = next(item for item in snapshot["tracks"] if item["filename"] == "idle.bvh")

        with self._post("/api/categories/create", {"name": "战斗音效", "accent": "#C85A3A"}) as response:
            created = json.loads(response.read().decode("utf-8"))
        category = created["category"]
        self.assertEqual(category["domain"], "custom")
        self.assertEqual(len(created["library"]["categories"]), 16)

        with self._post(
            "/api/category/set",
            {"ids": [bvh["id"]], "category": category["key"]},
        ) as response:
            moved = json.loads(response.read().decode("utf-8"))
        row = next(item for item in moved["library"]["tracks"] if item["id"] == bvh["id"])
        self.assertEqual(row["category"]["key"], category["key"])

        with self._post(
            "/api/subcategory/set",
            {"ids": [audio["id"]], "subcategory": "attack"},
        ) as response:
            subtagged = json.loads(response.read().decode("utf-8"))
        row = next(item for item in subtagged["library"]["tracks"] if item["id"] == audio["id"])
        self.assertEqual(row["category"]["subcategory"]["key"], "attack")

        with self._get(f"/api/motion/{bvh['id']}") as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["motion"]["frame_count"], 2)
        self.assertTrue(payload["motion"]["frames"])

    def test_add_and_remove_folder_endpoints(self) -> None:
        extra = tempfile.TemporaryDirectory()
        self.addCleanup(extra.cleanup)
        make_wav(Path(extra.name) / "02.wav")
        with self._post("/api/library/add", {"path": extra.name}) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(len(payload["library"]["sources"]), 2)
        self.assertEqual(payload["library"]["stats"]["total"], 5)
        source_id = payload["library"]["sources"][1]["id"]
        with self._post("/api/library/remove", {"source_id": source_id}) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(len(payload["library"]["sources"]), 1)
        self.assertEqual(payload["library"]["stats"]["total"], 4)

    def test_audio_range(self) -> None:
        track = next(
            item for item in self.state.library.snapshot()["tracks"] if item["kind"] == "audio"
        )
        with self._get(track["stream_url"], {"Range": "bytes=0-3"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"RIFF")
            self.assertEqual(response.headers["Content-Range"].split("/")[-1], str(track["size"]))


if __name__ == "__main__":
    unittest.main()
