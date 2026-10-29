// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import ObjectState, { SerializedData } from '../object-state';
import config from '../config';
import { getSaveAction } from '../annotations-history';
import type { Label } from '../labels';
import { MaskShape } from './mask-shape';
import { ArgumentError } from '../exceptions';
import { ShapeType, HistoryActions } from '../enums';
import { SerializedShape } from '../server-response-types';
import { Shape } from './shape';
import { AnnotationInjection } from './types';
// eslint-disable-next-line import/no-cycle
import { shapeFactory } from './index';

/** One instance with independently editable rectangle and mask components. */
export class BBoxMaskShape extends Shape {
    public elements: Shape[];
    private injection: AnnotationInjection;

    constructor(data: SerializedShape, clientID: number, color: string, injection: AnnotationInjection) {
        super(data, clientID, color, injection);
        this.shapeType = ShapeType.BBOX_MASK;
        this.points = [];
        this.rotation = 0;
        this.pinned = true;
        this.readOnlyFields = ['points', 'rotation', 'pinned'];
        this.injection = { ...injection, parentId: clientID };
        this.elements = data.elements.map((element) => this.makeElement(element));
    }

    private makeElement(data: SerializedShape['elements'][0]): Shape {
        const element = shapeFactory({
            ...data,
            points: [...data.points],
            frame: this.frame,
            label_id: this.label.id,
            group: this.group,
            z_order: this.zOrder,
            source: data.source ?? this.source,
        }, this.nextClientID(), this.injection);
        element.lock = element.shapeType === ShapeType.RECTANGLE;
        return element;
    }

    public get(frame: number): ReturnType<Shape['get']> & { elements: SerializedData[] } {
        return {
            ...super.get(frame),
            hidden: this.elements.filter((element) => !element.removed)
                .every((element) => element.hidden),
            updated: Math.max(this.updated, ...this.elements.map((element) => element.updated)),
            elements: this.elements.filter((element) => !element.removed).map((element) => ({
                ...element.get(frame),
                updated: Math.max(this.updated, element.updated),
                label: this.label,
                color: this.color,
                group: this.groupObject,
                zOrder: this.zOrder,
                annSources: this.annSources,
                lock: this.lock || element.lock,
                outside: this.outside || element.outside,
            })),
        };
    }

    public toJSON(): SerializedShape {
        return {
            ...super.toJSON(),
            elements: this.elements.filter((element) => !element.removed).map((element) => ({
                ...element.toJSON(),
                group: this.group,
                z_order: this.zOrder,
                frame: this.frame,
            })),
        };
    }

    public get removed(): boolean {
        return super.removed || this.elements.every((element) => element.removed);
    }

    public set removed(value: boolean) {
        super.removed = value;
    }

    public clearServerId(): void {
        super.clearServerId();
        this.elements.forEach((element) => element.clearServerId());
    }

    public updateFromServerResponse(body: { id: number; elements?: SerializedShape['elements'] }): void {
        super.updateFromServerResponse(body);
        body.elements?.forEach((element) => {
            this.elements.find((candidate) => !candidate.removed && candidate.shapeType === element.type)
                ?.updateFromServerResponse({ id: element.id });
        });
    }

    protected saveHidden(hidden: boolean, frame: number): void {
        for (const element of this.elements.filter((part) => !part.removed)) {
            const state = new ObjectState(element.get(frame));
            state.hidden = hidden;
            element.save(frame, state);
        }
    }

    protected saveLabel(label: Label, frame: number): void {
        super.saveLabel(label, frame);
        for (const element of this.elements) {
            const state = new ObjectState(element.get(frame));
            state.label = label;
            const { lock } = element;
            try {
                element.lock = false;
                element.save(frame, state);
            } finally {
                element.lock = lock;
            }
        }
    }

    public save(frame: number, data: ObjectState): ObjectState {
        if (this.lock && data.lock && !data.updateFlags.hidden) return super.save(frame, data);
        const { elements } = data;
        if (data.updateFlags.elements) {
            const types = elements.map((element) => element.shapeType);
            if (!types.length || new Set(types).size !== types.length ||
                types.some((type) => ![ShapeType.RECTANGLE, ShapeType.MASK].includes(type)) ||
                elements.some((element) => element.frame !== frame || element.label.id !== data.label.id)) {
                throw new ArgumentError('Expected one rectangle and/or one mask with the same frame and label');
            }
        }
        const ownsTransaction = this.history.beginTransaction(getSaveAction([data]) ?? HistoryActions.CHANGED_OBJECTS);
        try {
            if (this.lock && data.lock) return super.save(frame, data);
            if (data.updateFlags.elements) {
                const previous = this.elements;
                const next = elements.map((state) => {
                    if (state.clientID !== null) {
                        const element = previous.find((candidate) => candidate.clientID === state.clientID);
                        if (!element) throw new ArgumentError('Component does not belong to this instance');
                        return element;
                    }
                    return this.makeElement({
                        type: state.shapeType,
                        points: state.points,
                        frame,
                        label_id: data.label.id,
                        attributes: [],
                        occluded: state.occluded,
                        outside: false,
                        rotation: 0,
                        z_order: data.zOrder,
                        group: this.group,
                        source: state.source,
                    });
                });
                const apply = (value: Shape[]): void => {
                    this.elements = value;
                    this.updated = Date.now();
                };
                this.history.do(HistoryActions.CHANGED_ELEMENTS,
                    () => apply(previous), () => apply(next), [this.clientID], frame);
                apply(next);
                if (config.removeUnderlyingMaskPixels.enabled) {
                    for (const element of next) {
                        if (element instanceof MaskShape && !previous.includes(element)) {
                            const {
                                undo, redo, clientIDs, emptyMaskOccurred,
                            } = element.removeUnderlyingPixels(frame);
                            this.history.do(HistoryActions.CHANGED_POINTS, undo, redo, clientIDs, frame);
                            if (emptyMaskOccurred) config.removeUnderlyingMaskPixels.onEmptyMaskOccurrence();
                        }
                    }
                }
            }
            for (const state of elements) {
                if (state.clientID !== null) {
                    this.elements.find((element) => element.clientID === state.clientID)?.save(frame, state);
                }
            }
            return super.save(frame, data);
        } catch (error: unknown) {
            if (ownsTransaction) this.history.abortTransaction();
            throw error;
        } finally {
            if (ownsTransaction) this.history.endTransaction();
        }
    }
}
