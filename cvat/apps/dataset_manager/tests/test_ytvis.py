import json
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import datumaro as dm
import numpy as np
from django.db import transaction
from django.test import TestCase
from pycocotools import mask as mask_utils

from cvat.apps.dataset_manager.bindings import CvatExportError, CvatImportError, MediaProvider2D
from cvat.apps.dataset_manager.formats.registry import make_exporter, make_importer
from cvat.apps.dataset_manager.formats.transformations import MaskConverter
from cvat.apps.dataset_manager.task import JobAnnotation, TaskAnnotation
from cvat.apps.engine import models
from cvat.apps.engine.backup import TaskExporter, TaskImporter


class YtvisTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        data = models.Data.objects.create(size=3, stop_frame=2, image_quality=75)
        cls.task = models.Task.objects.create(name="YTVIS", data=data, mode="annotation", overlap=0)
        cls.label = models.Label.objects.create(task=cls.task, name="person")
        for name in ("video_id", "instance_id"):
            models.AttributeSpec.objects.create(
                label=cls.label, name=name, input_type="text", mutable=False
            )
        for start, stop in ((0, 1), (2, 2)):
            segment = models.Segment.objects.create(
                task=cls.task, start_frame=start, stop_frame=stop
            )
            models.Job.objects.create(segment=segment)
        for frame in range(3):
            models.Image.objects.create(
                data=data,
                path=f"dancetrack0041__p1/{frame + 1:08d}.jpg",
                frame=frame,
                width=20,
                height=20,
            )

    def setUp(self) -> None:
        events = patch("cvat.apps.dataset_manager.task.handle_annotations_change")
        events.start()
        self.addCleanup(events.stop)
        self.mask = np.zeros((20, 20), dtype=np.uint8)
        self.mask[5:9, 6:11] = 1
        segmentation = mask_utils.encode(np.asfortranarray(self.mask))
        segmentation["counts"] = segmentation["counts"].decode()
        video = {
            "id": 9,
            "name": "dancetrack0041__p1",
            "length": 3,
            "height": 20,
            "width": 20,
            "fps": 20,
            "source_video_id": 13,
            "file_names": [f"dancetrack0041__p1/{frame + 1:08d}.jpg" for frame in range(3)],
        }
        self.source = {
            "info": {"version": "v3"},
            "videos": [{**video, "id": 1, "file_names": ["other/1.jpg"]}, video],
            "categories": [{"id": 1, "name": "person"}],
            "annotations": [
                {
                    "id": 55,
                    "video_id": 9,
                    "category_id": 1,
                    "iscrowd": 0,
                    "bboxes": [[1.25, 2.5, 15, 16], [2, 3, 14, 15], None],
                    "segmentations": [segmentation, None, None],
                    "areas": [20, None, None],
                    "source_track_id": 106,
                    "source_visibilities": [1.0, 0.5, None],
                },
                {
                    "id": 76,
                    "video_id": 9,
                    "category_id": 1,
                    "iscrowd": 0,
                    "bboxes": [None, None, [5, 1, 12, 18]],
                    "segmentations": [None, None, segmentation],
                    "areas": [None, None, 20],
                },
            ],
        }

    def _import(
        self, source: dict | None = None, *, use_zip: bool = False, format_name: str = "YTVIS 1.0"
    ) -> None:
        with tempfile.TemporaryDirectory() as directory, transaction.atomic():
            path = Path(directory) / ("input.zip" if use_zip else "input.json")
            payload = json.dumps(self.source if source is None else source)
            if use_zip:
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("annotations/instances.json", payload)
            else:
                path.write_text(payload)
            with path.open("rb") as stream:
                TaskAnnotation(self.task.id).import_annotations(stream, make_importer(format_name))

    def _export(self, *, save_images: bool = False) -> dict:
        ann = TaskAnnotation(self.task.id)
        ann.init_from_db(streaming=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "output.zip"
            with path.open("wb") as stream:
                ann.export(
                    stream,
                    make_exporter("YTVIS 1.0"),
                    temp_dir=str(root / "dataset"),
                    save_images=save_images,
                )
            with zipfile.ZipFile(path) as archive:
                if save_images:
                    self.assertEqual(
                        {name for name in archive.namelist() if name.startswith("images/")},
                        {f"images/{name}" for name in self.source["videos"][1]["file_names"]},
                    )
                return json.loads(archive.read("annotations/instances.json"))

    def test_round_trip_across_jobs(self) -> None:
        for use_zip in (False, True):
            with self.subTest(use_zip=use_zip):
                self._import(use_zip=use_zip)
                self.assertEqual(models.LabeledShapeSource.objects.count(), 3)
                self.assertEqual(models.LabeledShape.objects.filter(type="rectangle").count(), 1)
                output = self._export()
                self.assertEqual(output, {**self.source, "videos": [self.source["videos"][1]]})
                metadata = models.TaskAnnSource.objects.get(task=self.task).data["data"]
                self.assertEqual(metadata["annotations"][0]["segmentations"], [None] * 3)

    def test_fill_missing_mask_keeps_source_boxes(self) -> None:
        self._import()
        rectangle = models.LabeledShape.objects.get(type="rectangle")
        anns = JobAnnotation(rectangle.job_id)
        anns.init_from_db()
        reference = next(shape for shape in anns.data["shapes"] if shape["type"] == "rectangle")
        new_mask = deepcopy(reference)
        new_mask.pop("id")
        new_mask.pop("ann_sources")
        new_mask["type"] = "mask"
        new_mask["points"] = MaskConverter.dm_mask_to_cvat_rle(dm.Mask(self.mask))
        anns.create({"shapes": [new_mask], "tracks": [], "tags": [], "intervals": []})
        output = self._export()
        for actual, original in zip(output["annotations"], self.source["annotations"]):
            self.assertEqual(actual["id"], original["id"])
            self.assertEqual(actual["bboxes"], original["bboxes"])
        track = output["annotations"][0]
        self.assertEqual(track["areas"], [20, 20, None])
        np.testing.assert_array_equal(mask_utils.decode(track["segmentations"][1]), self.mask)

    def test_invalid_import_rolls_back(self) -> None:
        self._import()
        original = self._export()
        invalid = deepcopy(self.source)
        invalid["annotations"][0]["bboxes"].pop()
        with self.assertRaises(CvatImportError):
            self._import(invalid)
        self.assertEqual(self._export(), original)

    def test_edit_and_delete_mask_preserves_gt(self) -> None:
        self._import()
        original = models.LabeledShape.objects.filter(type="mask", frame=0).get()
        anns = JobAnnotation(original.job_id)
        anns.init_from_db()
        mask = next(shape for shape in anns.data["shapes"] if shape["id"] == original.id)
        edited = np.zeros_like(self.mask)
        edited[12:16, 10:13] = 1
        mask["points"] = MaskConverter.dm_mask_to_cvat_rle(dm.Mask(edited))
        anns.update(deepcopy(anns.data))
        track = self._export()["annotations"][0]
        np.testing.assert_array_equal(mask_utils.decode(track["segmentations"][0]), edited)
        self.assertEqual(track["areas"][0], 12)
        self.assertEqual(track["bboxes"], self.source["annotations"][0]["bboxes"])
        anns.delete({"shapes": [{"id": original.id}], "tracks": [], "tags": [], "intervals": []})
        track = self._export()["annotations"][0]
        self.assertEqual(track["segmentations"], [None] * 3)
        self.assertEqual(track["bboxes"], self.source["annotations"][0]["bboxes"])

    def test_frame_paths_and_image_export(self) -> None:
        # Task frame order can differ from YTVIS; matching must use the complete paths.
        images = list(self.task.data.images.order_by("frame"))
        images[0].path, images[2].path = images[2].path, images[0].path
        models.Image.objects.bulk_update(images, ["path"])
        self._import()
        with patch.object(
            MediaProvider2D,
            "get_media_for_frame",
            return_value=dm.Image.from_numpy(data=np.zeros((20, 20, 3), dtype=np.uint8)),
        ) as media:
            self.assertEqual(
                self._export(save_images=True),
                {**self.source, "videos": [self.source["videos"][1]]},
            )
            self.assertEqual(media.call_count, 3)
        invalid = deepcopy(self.source)
        invalid["videos"][1]["file_names"][0] = "other/00000001.jpg"
        with self.assertRaisesRegex(CvatImportError, "complete video"):
            self._import(invalid)

    def test_backup_source_metadata(self) -> None:
        self._import()
        source = models.TaskAnnSource.objects.get(task=self.task).data
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.zip"
            with zipfile.ZipFile(path, "w") as archive:
                TaskExporter(self.task.id, lightweight=False)._write_manifest(archive, "")
                archive.writestr("annotations.json", "[]")
            importer = TaskImporter(str(path), user_id=None)
        self.assertNotIn("ann_sources", importer._manifest)
        restored_task = models.Task.objects.create(name="restored")
        # Media/job restoration is unchanged; exercise the new metadata round trip in isolation.
        importer._db_task = restored_task
        with patch.object(importer, "_import_task"), patch.object(importer, "_import_annotations"):
            importer.import_task()
        self.assertEqual(models.TaskAnnSource.objects.get(task=restored_task).data, source)

    def test_export_rejects_duplicate_masks(self) -> None:
        self._import()
        original = models.LabeledShape.objects.filter(type="mask").first()
        anns = JobAnnotation(original.job_id)
        anns.init_from_db()
        duplicate = deepcopy(
            next(shape for shape in anns.data["shapes"] if shape["type"] == "mask")
        )
        duplicate.pop("id")
        anns.create({"shapes": [duplicate], "tracks": [], "tags": [], "intervals": []})
        with self.assertRaisesRegex(CvatExportError, "duplicate mask"):
            self._export()

    def test_source_identity_and_replacement_import(self) -> None:
        self._import()
        instance_attr = self.label.attributespec_set.get(name="instance_id")
        values = models.LabeledShapeAttributeVal.objects.filter(spec=instance_attr)
        values.update(value="")
        # Imported identities remain linked even if their display attributes are missing.
        self.assertEqual(self._export()["annotations"], self.source["annotations"])
        values.update(value="999")
        with self.assertRaisesRegex(CvatExportError, "source identity"):
            self._export()

        self._import(
            {
                "images": [
                    {
                        "id": 1,
                        "file_name": self.source["videos"][1]["file_names"][0],
                        "height": 20,
                        "width": 20,
                    }
                ],
                "annotations": [],
                "categories": self.source["categories"],
            },
            format_name="COCO 1.0",
        )
        self.assertFalse(models.TaskAnnSource.objects.filter(task=self.task).exists())
        self.assertFalse(models.LabeledShapeSource.objects.exists())
        with self.assertRaisesRegex(CvatExportError, "Import YTVIS first"):
            self._export()
