// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import type { SerializedShape } from './server-response-types';

export type AnnSources = SerializedShape['ann_sources'];

export interface AnnIdentity {
    key: string;
    fields: Readonly<Record<string, number>>;
}

// Format-specific source interpretation stays here, outside object and canvas code.
export function getAnnIdentity(source: AnnSources): AnnIdentity | null {
    if (source?.format === 'YTVIS 1.0') {
        const { video_id: videoID, instance_id: instanceID } = source.data;
        if (typeof videoID === 'number' && Number.isSafeInteger(videoID) && videoID >= 0 &&
            typeof instanceID === 'number' && Number.isSafeInteger(instanceID) && instanceID >= 0) {
            return {
                key: JSON.stringify([source.format, videoID, instanceID]),
                fields: { video_id: videoID, instance_id: instanceID },
            };
        }
    }
    return null;
}

export function getAnnColor(source: AnnSources, palette: readonly string[], fallback: string): string {
    const identity = getAnnIdentity(source);
    if (!identity) return fallback;
    let hash = 0;
    for (const char of identity.key) {
        hash = (hash * 31 + char.charCodeAt(0)) % 4294967291;
    }
    return palette[hash % palette.length];
}
