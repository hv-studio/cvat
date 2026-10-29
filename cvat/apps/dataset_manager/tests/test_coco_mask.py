import json
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import datumaro as dm
import numpy as np
from django.test import TestCase
from pycocotools import mask as mask_utils

from cvat.apps.dataset_manager.annotation import AnnotationIR
from cvat.apps.dataset_manager.bindings import TaskData
from cvat.apps.dataset_manager.formats.registry import make_exporter, make_importer
from cvat.apps.dataset_manager.formats.transformations import MaskConverter
from cvat.apps.dataset_manager.task import JobAnnotation
from cvat.apps.engine import models


class CocoMaskTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        data = models.Data.objects.create(size=1, stop_frame=0, image_quality=75)
        cls.task = models.Task.objects.create(name="reference bbox", data=data, mode="annotation")
        cls.label = models.Label.objects.create(task=cls.task, name="person")
        segment = models.Segment.objects.create(task=cls.task, start_frame=0, stop_frame=0)
        cls.job = models.Job.objects.create(segment=segment)
        models.Image.objects.create(data=data, path="frame.jpg", frame=0, width=20, height=20)

    def setUp(self) -> None:
        events = patch("cvat.apps.dataset_manager.task.handle_annotations_change")
        events.start()
        self.addCleanup(events.stop)
        self.anns = JobAnnotation(self.job.id)
        self.mask = np.zeros((20, 20), dtype=np.uint8)
        self.mask[5:9, 6:11] = 1
        self.bbox = [1.25, 2.5, 15.0, 16.0]

    def _import(self, *, use_zip: bool = False) -> None:
        segmentation = mask_utils.encode(np.asfortranarray(self.mask))
        segmentation["counts"] = segmentation["counts"].decode()
        source = {
            "images": [{"id": 1, "file_name": "frame.jpg", "width": 20, "height": 20}],
            "categories": [{"id": 1, "name": "person"}],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 1,
                    "iscrowd": 0,
                    "bbox": self.bbox,
                    "segmentation": segmentation,
                    "area": 20,
                },
                {
                    "id": 2,
                    "image_id": 1,
                    "category_id": 1,
                    "iscrowd": 0,
                    "bbox": [0, 0, 2, 3],
                    "segmentation": [],
                    "area": 6,
                },
            ],
        }
        task_data = TaskData(annotation_ir=AnnotationIR(self.task.dimension), db_task=self.task)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_file = root / ("input.zip" if use_zip else "input.json")
            if use_zip:
                with zipfile.ZipFile(source_file, "w") as archive:
                    archive.writestr("annotations/instances_default.json", json.dumps(source))
            else:
                source_file.write_text(json.dumps(source))
            unpacked = root / "unpacked"
            unpacked.mkdir()
            with source_file.open("rb") as source_stream:
                make_importer("COCO 1.0")(source_stream, str(unpacked), task_data)
        self.anns.put(task_data.data.serialize())
        self.anns.init_from_db()

    def _export(self) -> dict:
        task_data = TaskData(annotation_ir=self.anns.ir_data, db_task=self.task)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output.zip"
            with output.open("wb") as stream:
                make_exporter("COCO 1.0")(stream, str(root / "dataset"), task_data)
            with zipfile.ZipFile(output) as archive:
                filename = next(name for name in archive.namelist() if name.endswith(".json"))
                return json.loads(archive.read(filename))

    def test_coco_round_trip_and_mask_edit(self) -> None:
        for use_zip in (False, True):
            with self.subTest(use_zip=use_zip):
                self._import(use_zip=use_zip)
                shapes = self.anns.data["shapes"]
                mask = next(shape for shape in shapes if shape["type"] == "mask")
                rectangle = next(shape for shape in shapes if shape["type"] == "rectangle")
                self.assertNotIn("ann_sources", mask)
                self.assertNotIn("ann_sources", rectangle)
                self.assertEqual(models.LabeledShapeSource.objects.count(), 0)

                edited_mask = np.zeros((20, 20), dtype=np.uint8)
                edited_mask[12:16, 10:13] = 1
                mask["points"] = MaskConverter.dm_mask_to_cvat_rle(dm.Mask(edited_mask))
                self.anns.update(deepcopy(self.anns.data))
                self.anns.init_from_db()

                exported = self._export()["annotations"]
                self.assertEqual(len(exported), 2)
                exported_mask = next(item for item in exported if item["segmentation"])
                self.assertEqual(exported_mask["bbox"], [10, 12, 3, 4])
                segmentation = exported_mask["segmentation"]
                if isinstance(segmentation["counts"], list):
                    segmentation = mask_utils.frPyObjects(segmentation, 20, 20)
                np.testing.assert_array_equal(mask_utils.decode(segmentation), edited_mask)
                self.assertEqual(exported_mask["area"], int(edited_mask.sum()))
                self.assertNotIn("__cvat_ann_sources", exported_mask.get("attributes", {}))
                exported_box = next(item for item in exported if not item["segmentation"])
                self.assertEqual(exported_box["bbox"], [0, 0, 2, 3])
