"""
Upgrade source metadata from backups made before the generic source associations.
"""


def upgrade_ann_sources(manifest: dict, anns: list[dict]) -> None:
    """Normalize historical backup fields at the import boundary."""
    if "ytvis_source" in manifest:
        manifest["ann_sources"] = {
            "format": "YTVIS 1.0",
            "data": manifest.pop("ytvis_source"),
        }

    for job in anns:
        pending = list(job.get("shapes", []))
        while pending:
            shape = pending.pop()
            pending.extend(shape.get("elements", []))
            if "source_bbox" in shape:
                bbox = shape.pop("source_bbox")
                if bbox is not None:
                    shape["ann_sources"] = {"format": "COCO 1.0", "data": {"ref_bbox": bbox}}
