// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/** Convert a CVAT RLE mask (including its bounding box) to SAM mask-prompt logits. */
export default function maskToInput(
    rle: number[], width: number, height: number, roi?: [number, number, number, number],
): Float32Array {
    const [left, top, right, bottom] = rle.slice(-4);
    const maskWidth = right - left + 1;
    const maskHeight = bottom - top + 1;
    const mask = new Uint8Array(maskWidth * maskHeight);
    let offset = 0;
    for (let index = 0; index < rle.length - 4; index++) {
        const end = offset + rle[index];
        if (index % 2) mask.fill(1, offset, end);
        offset = end;
    }

    const [x, y, xbr, ybr] = roi ?? [0, 0, width, height];
    const inputWidth = xbr - x;
    const inputHeight = ybr - y;
    const scale = 1024 / Math.max(inputWidth, inputHeight);
    // SAM resizes the longest side to 1024, rounding the other side, then pads right/bottom.
    const resizedWidth = Math.round(inputWidth * scale);
    const resizedHeight = Math.round(inputHeight * scale);
    const sample = (px: number, py: number): number => {
        const sx = Math.max(x, Math.min(xbr - 1, px));
        const sy = Math.max(y, Math.min(ybr - 1, py));
        return sx < left || sx > right || sy < top || sy > bottom ?
            0 : mask[(sy - top) * maskWidth + sx - left];
    };

    // Binary annotations have no saved logits. Use finite foreground/background logits
    // and bilinear interpolation so subsequent point prompts can still change the boundary.
    const result = new Float32Array(256 * 256).fill(-6);
    for (let row = 0; row < 256; row++) {
        for (let col = 0; col < 256; col++) {
            if ((col + 0.5) * 4 >= resizedWidth || (row + 0.5) * 4 >= resizedHeight) continue;
            const sx = (((col + 0.5) * 4) / resizedWidth) * inputWidth - 0.5 + x;
            const sy = (((row + 0.5) * 4) / resizedHeight) * inputHeight - 0.5 + y;
            const x0 = Math.floor(sx);
            const y0 = Math.floor(sy);
            const dx = sx - x0;
            const dy = sy - y0;
            const value = (1 - dy) * ((1 - dx) * sample(x0, y0) + dx * sample(x0 + 1, y0)) +
                dy * ((1 - dx) * sample(x0, y0 + 1) + dx * sample(x0 + 1, y0 + 1));
            result[row * 256 + col] = value * 12 - 6;
        }
    }

    return result;
}
