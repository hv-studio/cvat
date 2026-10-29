"""
Import and export a complete YTVIS video for mask refinement.
"""

import json
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import datumaro as dm
from pycocotools import mask as mask_utils

from cvat.apps.dataset_manager.bindings import (
    CvatExportError,
    CvatImportError,
    GetCVATDataExtractor,
    TaskData,
)
from cvat.apps.dataset_manager.util import make_zip_archive
from cvat.apps.engine import models

from .registry import exporter, importer
from .transformations import MaskConverter, validate_ref_bbox


def _match_video(source: dict, instance_data: TaskData) -> tuple[dict, list[int]]:
    paths = {info["path"]: frame for frame, info in instance_data.frame_info.items()}
    matches = [
        video
        for video in source["videos"]
        if len(video["file_names"]) == len(paths) and set(video["file_names"]) == set(paths)
    ]
    if len(matches) != 1 or instance_data.deleted_frames:
        raise ValueError(
            "YTVIS requires one complete video matching the task's image paths. "
            "Upload the original frames with their video directory; do not skip or delete frames."
        )
    video = matches[0]
    if video["length"] != len(paths):
        raise ValueError("YTVIS video length does not match file_names")
    frames = [paths[name] for name in video["file_names"]]
    for name, frame in zip(video["file_names"], frames):
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            raise ValueError(f"Invalid YTVIS image path: {name}")
        info = instance_data.frame_info[frame]
        if (info["height"], info["width"]) != (video["height"], video["width"]):
            raise ValueError(f"YTVIS image dimensions do not match: {name}")
    return video, frames


@importer(name="YTVIS", ext="JSON, ZIP", version="1.0")
def _import_ytvis(
    src_file: BinaryIO, temp_dir: str, instance_data, load_data_callback=None, **kwargs
) -> None:
    if not isinstance(instance_data, TaskData) or load_data_callback is not None:
        raise CvatImportError("Import YTVIS annotations on a task containing one video's images")
    if zipfile.is_zipfile(src_file):
        with zipfile.ZipFile(src_file) as archive:
            filenames = [name for name in archive.namelist() if name.endswith(".json")]
            if len(filenames) != 1:
                raise CvatImportError("A YTVIS archive must contain exactly one annotation JSON")
            with archive.open(filenames[0]) as stream:
                source = json.load(stream)
    else:
        src_file.seek(0)
        source = json.load(src_file)

    try:
        video, frames = _match_video(source, instance_data)
    except ValueError as error:
        raise CvatImportError(str(error)) from error
    tracks = [track for track in source["annotations"] if track["video_id"] == video["id"]]
    if len({track["id"] for track in tracks}) != len(tracks):
        raise CvatImportError("YTVIS track IDs must be unique")
    categories = {category["id"]: category["name"] for category in source["categories"]}
    if len(categories) != len(source["categories"]):
        raise CvatImportError("YTVIS category IDs must be unique")

    task = instance_data.db_instance
    labels = {label.name: label for label in task.get_labels(prefetch=True)}
    for category_id in {track["category_id"] for track in tracks}:
        name = categories[category_id]
        if name not in labels:
            raise CvatImportError(f"Create the task label {name!r} before importing YTVIS")

    if models.LabeledShape.objects.filter(job__segment__task=task).exists():
        raise CvatImportError(
            "Use replacement import for YTVIS; appending would duplicate instances"
        )

    length = video["length"]
    for track in tracks:
        segmentations = track.get("segmentations", [None] * length)
        if len(track["bboxes"]) != length or len(segmentations) != length:
            raise CvatImportError(f"Invalid frame array length in YTVIS track {track['id']}")
        if "areas" in track and len(track["areas"]) != length:
            raise CvatImportError(f"Invalid areas length in YTVIS track {track['id']}")
        for index, (bbox, segmentation) in enumerate(zip(track["bboxes"], segmentations)):
            if bbox is not None:
                try:
                    validate_ref_bbox(bbox)
                except ValueError as error:
                    raise CvatImportError(
                        f"Invalid ref_bbox in track {track['id']}, frame {index}"
                    ) from error
            if segmentation is None and bbox is None:
                continue
            if segmentation is None:
                left, top, width, height = bbox
                points = [left, top, left + width, top + height]
                shape_type = models.ShapeType.RECTANGLE
            else:
                if not isinstance(segmentation, dict) or segmentation.get("size") != [
                    video["height"],
                    video["width"],
                ]:
                    raise CvatImportError(
                        f"Expected a full-image COCO RLE in track {track['id']}, frame {index}"
                    )
                try:
                    if isinstance(segmentation["counts"], list):
                        segmentation = mask_utils.frPyObjects(
                            segmentation, video["height"], video["width"]
                        )
                    points = MaskConverter.dm_mask_to_cvat_rle(dm.RleMask(rle=segmentation))
                except (KeyError, TypeError, ValueError) as error:
                    raise CvatImportError(
                        f"Invalid RLE in track {track['id']}, frame {index}"
                    ) from error
                shape_type = models.ShapeType.MASK
            instance_data.add_shape(
                instance_data.LabeledShape(
                    type=shape_type,
                    frame=instance_data.abs_frame_id(frames[index]),
                    label=categories[track["category_id"]],
                    points=points,
                    occluded=False,
                    attributes=[],
                    source=models.SourceType.FILE,
                    ann_sources={
                        "format": "YTVIS 1.0",
                        "data": {
                            "video_id": video["id"],
                            "instance_id": track["id"],
                            "ref_bbox": bbox,
                        },
                    },
                )
            )
        # Keep identities, GT boxes and provenance without storing a second copy of the masks.
        track["segmentations"] = [None] * length
        track["areas"] = [None] * length

    models.TaskAnnSource.objects.update_or_create(
        task=task,
        defaults={
            "data": {
                "format": "YTVIS 1.0",
                "data": {**source, "videos": [video], "annotations": tracks},
            }
        },
    )


@exporter(name="YTVIS", ext="ZIP", version="1.0")
def _export_ytvis(
    dst_file: BinaryIO, temp_dir: str, instance_data, save_images: bool = False
) -> None:
    if not isinstance(instance_data, TaskData):
        raise CvatExportError("Export YTVIS from the task to include the complete video")
    source = models.TaskAnnSource.objects.filter(task=instance_data.db_instance).first()
    if source is None or source.data["format"] != "YTVIS 1.0":
        raise CvatExportError("Import YTVIS first to retain video metadata and original track IDs")
    output = deepcopy(source.data["data"])
    try:
        video, frames = _match_video(output, instance_data)
    except ValueError as error:
        raise CvatExportError(str(error)) from error
    frame_indices = {frame: index for index, frame in enumerate(frames)}
    tracks = {str(track["id"]): track for track in output["annotations"]}
    categories = {category["id"]: category["name"] for category in output["categories"]}
    for frame in instance_data.group_by_frame(include_empty=True):
        index = frame_indices[frame.idx]
        for shape in frame.labeled_shapes:
            source = getattr(shape, "ann_sources", None)
            if not source or source["format"] != "YTVIS 1.0":
                raise CvatExportError(f"Frame {index}: each object needs a YTVIS source identity")
            identity = source["data"]
            instance_id = str(identity.get("instance_id"))
            if identity.get("video_id") != video["id"] or instance_id not in tracks:
                raise CvatExportError(
                    f"Frame {index}: source identity does not belong to this video"
                )
            track = tracks[instance_id]
            if shape.label != categories[track["category_id"]]:
                raise CvatExportError(f"Frame {index}: label does not match track {instance_id}")
            if shape.type == models.ShapeType.RECTANGLE:
                # Missing-mask reference boxes never replace the original GT boxes.
                continue
            if shape.type != models.ShapeType.MASK:
                raise CvatExportError(
                    f"Frame {index}: YTVIS requires masks or reference rectangles"
                )
            if track["segmentations"][index] is not None:
                raise CvatExportError(f"Frame {index}: duplicate mask for track {instance_id}")
            mask = MaskConverter.cvat_rle_to_dm_rle(
                shape._replace(label=track["category_id"], attributes={}), frame.height, frame.width
            )
            track["segmentations"][index] = {
                "size": list(mask.rle["size"]),
                "counts": mask.rle["counts"].decode("ascii"),
            }
            track["areas"][index] = int(mask_utils.area(mask.rle))

    root = Path(temp_dir)
    anns_dir = root / "annotations"
    anns_dir.mkdir(parents=True, exist_ok=True)
    with (anns_dir / "instances.json").open("w", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, allow_nan=False)
    if save_images:
        with GetCVATDataExtractor(instance_data, include_images=True) as extractor:
            for item in extractor:
                frame = instance_data.rel_frame_id(item.attributes["frame"])
                name = video["file_names"][frame_indices[frame]]
                image_path = root / "images" / name
                image_path.parent.mkdir(parents=True, exist_ok=True)
                item.media.save(str(image_path))
    make_zip_archive(temp_dir, dst_file)
