// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Button from 'antd/lib/button';
import Popconfirm from 'antd/lib/popconfirm';
import { ShapeType } from 'cvat-core-wrapper';
import { Canvas } from 'cvat-canvas-wrapper';
import { ActiveControl, CombinedState } from 'reducers';
import { updateActiveControl, updateAnnotationsAsync, updateEditedStateAsync } from 'actions/annotation-actions';

/** Component actions keep geometry edits within the existing instance. */
export default function BBoxMaskControls(props: { clientID: number; elementID?: number }): JSX.Element | null {
    const { clientID, elementID } = props;
    const dispatch = useDispatch();
    const { states, canvas } = useSelector((state: CombinedState) => ({
        states: state.annotation.annotations.states,
        canvas: state.annotation.canvas.instance,
    }));
    const parent = states.find((state) => state.clientID === clientID);
    if (parent?.shapeType !== ShapeType.BBOX_MASK || !(canvas instanceof Canvas)) return null;
    const disabled = parent.lock || parent.hidden || parent.isGroundTruth;
    const element = parent.elements.find((state) => state.clientID === elementID);

    const edit = (type: ShapeType): void => {
        const existing = parent.elements.find((state) => state.shapeType === type);
        canvas.cancel();
        if (existing) {
            dispatch(updateActiveControl(ActiveControl.EDIT));
            canvas.edit({ enabled: true, state: existing });
        } else {
            dispatch(updateEditedStateAsync(parent));
            const control = type === ShapeType.MASK ? ActiveControl.DRAW_MASK : ActiveControl.DRAW_RECTANGLE;
            dispatch(updateActiveControl(control));
            canvas.draw({ enabled: true, shapeType: type });
        }
    };

    if (element) {
        return (
            <Popconfirm
                title={`Remove only this ${element.shapeType}? The other component will remain.`}
                onConfirm={() => {
                    parent.elements = parent.elements.filter((state) => state.clientID !== elementID);
                    dispatch(updateAnnotationsAsync([parent]));
                }}
                disabled={disabled || element.lock || parent.elements.length === 1}
            >
                <Button type='link' size='small' danger disabled={disabled || element.lock || parent.elements.length === 1}>
                    Remove component
                </Button>
            </Popconfirm>
        );
    }

    const mask = parent.elements.find((state) => state.shapeType === ShapeType.MASK);
    return (
        <div>
            <Button type='link' size='small' disabled={disabled || mask?.lock || mask?.hidden} onClick={() => edit(ShapeType.MASK)}>
                {mask ? 'Edit mask' : 'Draw mask'}
            </Button>
            {!parent.elements.some((state) => state.shapeType === ShapeType.RECTANGLE) && (
                <Button type='link' size='small' disabled={disabled} onClick={() => edit(ShapeType.RECTANGLE)}>
                    Draw bbox
                </Button>
            )}
        </div>
    );
}
