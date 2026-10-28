# Copyright (C) 2018-2022 Intel Corporation
# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import zipfile
from pathlib import Path
from typing import BinaryIO

from datumaro.components.annotation import AnnotationType, Bbox
from datumaro.components.dataset import StreamDataset
from datumaro.components.transformer import ItemTransform
from datumaro.plugins.data_formats.coco.base import CocoInstancesBase
from datumaro.plugins.data_formats.coco.importer import CocoImporter

from cvat.apps.dataset_manager.bindings import (
    ANN_SOURCES_ATTRIBUTE,
    CvatExportError,
    CvatToDmAnnotationConverter,
    GetCVATDataExtractor,
    NoMediaInAnnotationFileError,
    detect_dataset,
    import_dm_annotations,
)
from cvat.apps.dataset_manager.util import make_zip_archive

from .registry import dm_env, exporter, importer
from .transformations import EllipsesToMasks, validate_ref_bbox

_REQUIRE_ISCROWD = False


class CocoInstancesWithRefBbox(CocoInstancesBase):
    """Keep a mask's reference box while retaining Datumaro's streaming importer."""

    def _load_annotations(self, ann: dict, image_info=None, parsed_annotations=None) -> list:
        start = len(parsed_annotations) if parsed_annotations is not None else 0
        anns = super()._load_annotations(ann, image_info, parsed_annotations)
        masks = [item for item in anns[start:] if item.type == AnnotationType.mask]
        bbox = ann.get("bbox")
        if bbox is not None and masks:
            validate_ref_bbox(bbox)
            for mask in masks:
                mask.attributes[ANN_SOURCES_ATTRIBUTE] = {
                    "format": "COCO 1.0",
                    "data": {"ref_bbox": bbox},
                }
        return anns


dm_env.extractors.register("coco_instances", CocoInstancesWithRefBbox)


class CocoAnnConverter(CvatToDmAnnotationConverter):
    """Export reference boxes through Datumaro's grouped mask/box representation."""

    def _convert_shape(self, shape, *, index: int) -> list:
        anns = list(super()._convert_shape(shape, index=index))
        source = getattr(shape, "ann_sources", None)
        bbox = source["data"].get("ref_bbox") if source else None
        if shape.type == "mask" and bbox is not None:
            try:
                validate_ref_bbox(bbox)
            except ValueError as error:
                raise CvatExportError(str(error)) from error
            mask = anns[0]
            mask.group = mask.group or -(index + 1)
            anns.append(
                Bbox(*bbox, label=mask.label, group=mask.group, attributes=mask.attributes.copy())
            )
        return anns


def _convert_anns(*args, **kwargs) -> list:
    return CocoAnnConverter(*args, **kwargs).convert()


@exporter(name="COCO", ext="ZIP", version="1.0")
def _export_instances(dst_file, temp_dir, instance_data, save_images=False):
    with GetCVATDataExtractor(
        instance_data,
        include_images=save_images,
        format_type="coco_instances",
        convert_annotations=_convert_anns,
    ) as extractor:
        dataset = StreamDataset.from_extractors(extractor, env=dm_env)
        dataset.transform(EllipsesToMasks)
        dataset.export(temp_dir, "coco_instances", save_media=save_images, merge_images=False)

    make_zip_archive(temp_dir, dst_file)


@importer(name="COCO", ext="JSON, ZIP", version="1.0")
def _import_instances(
    src_file: BinaryIO, temp_dir, instance_data, load_data_callback=None, **kwargs
):
    if zipfile.is_zipfile(src_file):
        zipfile.ZipFile(src_file).extractall(temp_dir)
        # We use coco importer because it gives better error message
        detect_dataset(temp_dir, format_name="coco", importer=CocoImporter)
        dataset = StreamDataset.import_from(
            temp_dir, "coco_instances", env=dm_env, require_iscrowd=_REQUIRE_ISCROWD
        )
        if load_data_callback is not None:
            load_data_callback(dataset, instance_data)
        import_dm_annotations(dataset, instance_data)
    else:
        if load_data_callback:
            raise NoMediaInAnnotationFileError()

        annotation_file = Path(temp_dir) / "annotations" / "default.json"
        annotation_file.parent.mkdir()
        annotation_file.symlink_to(src_file.name)
        dataset = StreamDataset.import_from(
            str(annotation_file.absolute()),
            "coco_instances",
            env=dm_env,
            require_iscrowd=_REQUIRE_ISCROWD,
        )
        import_dm_annotations(dataset, instance_data)


@exporter(name="COCO Keypoints", ext="ZIP", version="1.0")
def _export_keypoints(dst_file, temp_dir, instance_data, save_images=False):
    with GetCVATDataExtractor(instance_data, include_images=save_images) as extractor:
        dataset = StreamDataset.from_extractors(extractor, env=dm_env)
        dataset.transform(EllipsesToMasks)
        dataset.export(
            temp_dir, "coco_person_keypoints", save_media=save_images, merge_images=False
        )

    make_zip_archive(temp_dir, dst_file)


class RemoveBboxAnnotations(ItemTransform):
    # Boxes would have invalid (skeleton) labels, so remove them
    # TODO: find a way to import boxes
    def transform_item(self, item):
        def convert_annotations():
            return [ann for ann in item.annotations if ann.type != AnnotationType.bbox]

        return item.wrap(annotations=convert_annotations)


@importer(name="COCO Keypoints", ext="JSON, ZIP", version="1.0")
def _import_keypoints(src_file, temp_dir, instance_data, load_data_callback=None, **kwargs):
    if zipfile.is_zipfile(src_file):
        zipfile.ZipFile(src_file).extractall(temp_dir)
        # We use coco importer because it gives better error message
        detect_dataset(temp_dir, format_name="coco", importer=CocoImporter)
        dataset = StreamDataset.import_from(
            temp_dir,
            "coco_person_keypoints",
            env=dm_env,
            require_iscrowd=_REQUIRE_ISCROWD,
        )
        dataset = dataset.transform(RemoveBboxAnnotations)
        if load_data_callback is not None:
            load_data_callback(dataset, instance_data)
        import_dm_annotations(dataset, instance_data)
    else:
        if load_data_callback:
            raise NoMediaInAnnotationFileError()

        annotation_file = Path(temp_dir) / "annotations" / "default.json"
        annotation_file.parent.mkdir()
        annotation_file.symlink_to(src_file.name)
        dataset = StreamDataset.import_from(
            str(annotation_file.absolute()),
            "coco_person_keypoints",
            env=dm_env,
            require_iscrowd=_REQUIRE_ISCROWD,
        )
        dataset = dataset.transform(RemoveBboxAnnotations)
        import_dm_annotations(dataset, instance_data)
