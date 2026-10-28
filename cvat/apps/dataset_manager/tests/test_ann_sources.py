import json
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from cvat.apps.dataset_manager.task import JobAnnotation
from cvat.apps.engine import models, serializers
from cvat.apps.engine.backup import TaskImporter, _TaskBackupBase


class AnnSourcesTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        data = models.Data.objects.create(size=1, stop_frame=0, image_quality=75)
        task = models.Task.objects.create(name="sources", data=data, mode="annotation")
        cls.label = models.Label.objects.create(task=task, name="object")
        segment = models.Segment.objects.create(task=task, start_frame=0, stop_frame=0)
        cls.job = models.Job.objects.create(segment=segment)
        models.Image.objects.create(data=data, path="frame.jpg", frame=0, width=20, height=20)

    def setUp(self) -> None:
        events = patch("cvat.apps.dataset_manager.task.handle_annotations_change")
        events.start()
        self.addCleanup(events.stop)
        self.anns = JobAnnotation(self.job.id)

    def test_opaque_metadata_lifecycle_and_backup(self) -> None:
        source = {
            "format": "test-format",
            "data": {"record": "original-7", "extra": {"values": [1, 2]}},
        }
        shape = {
            "type": "rectangle",
            "frame": 0,
            "label_id": self.label.id,
            "points": [0, 0, 5, 5],
            "ann_sources": source,
        }
        serializer = serializers.LabeledShapeSerializer(data=shape)
        serializer.is_valid(raise_exception=True)
        self.anns.create(
            {"shapes": [serializer.validated_data], "tags": [], "tracks": [], "intervals": []}
        )
        self.anns.init_from_db()
        shape = self.anns.data["shapes"][0]
        shape.pop("ann_sources")
        shape["points"] = [1, 1, 6, 6]
        self.anns.update(deepcopy(self.anns.data))
        self.anns.init_from_db()
        self.assertEqual(self.anns.data["shapes"][0]["ann_sources"], source)

        backup = _TaskBackupBase()._prepare_annotations(
            deepcopy(self.anns.data), {self.label.id: {"value": "object", "attributes": {}}}
        )
        backup = {key: list(value) for key, value in backup.items() if key != "version"}
        self.assertNotIn("id", backup["shapes"][0])
        restored = _TaskBackupBase()._prepare_annotations(
            backup, {"object": {"value": self.label.id, "attributes": {}}}
        )
        restored = {key: list(value) for key, value in restored.items()}
        serializer = serializers.LabeledDataSerializer(data=restored)
        serializer.is_valid(raise_exception=True)
        old_id = self.anns.data["shapes"][0]["id"]
        self.anns.put(serializer.validated_data)
        self.anns.init_from_db()
        self.assertNotEqual(self.anns.data["shapes"][0]["id"], old_id)
        self.assertEqual(self.anns.data["shapes"][0]["ann_sources"], source)
        self.anns.delete()
        self.assertFalse(models.LabeledShapeSource.objects.exists())

    def test_legacy_backup_upgrade(self) -> None:
        bbox = [1, 2, 3, 4]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "task.json", json.dumps({"version": "1.0", "ytvis_source": {"videos": []}})
                )
                archive.writestr(
                    "annotations.json", json.dumps([{"shapes": [{"source_bbox": bbox}]}])
                )
            importer = TaskImporter(str(path), user_id=None)
        self.assertEqual(importer._ann_sources, {"format": "YTVIS 1.0", "data": {"videos": []}})
        shape = importer._annotations[0]["shapes"][0]
        self.assertEqual(shape["ann_sources"]["data"]["ref_bbox"], bbox)
        self.assertNotIn("source_bbox", shape)
