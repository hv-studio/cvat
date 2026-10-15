// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Run from the repository root: node --test cvat-ui/plugins/sam/tests/refinement.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const { LRUCache } = require('lru-cache');

const sourceDirectory = path.resolve(__dirname, '../src/ts');
function loadTS(filename, imports = {}, globals = {}) {
    const source = fs.readFileSync(filename, 'utf8').replaceAll('import.meta.url', JSON.stringify(`file://${filename}`));
    const { outputText } = ts.transpileModule(source, {
        compilerOptions: {
            module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
            jsx: ts.JsxEmit.React, esModuleInterop: true,
        },
    });
    const exports = {};
    vm.runInNewContext(outputText, {
        exports,
        require: (name) => {
            assert.ok(Object.hasOwn(imports, name), `Unexpected import: ${name}`);
            return imports[name];
        },
        Uint8Array, Uint8ClampedArray, Float32Array, Int32Array, URL, console, setTimeout, clearTimeout, ...globals,
    }, { filename });
    return exports;
}
const { default: maskToInput } = loadTS(path.join(sourceDirectory, 'mask-input.ts'));

test('cropped masks retain their image position and SAM right/bottom padding', () => {
    const square = maskToInput([0, 64 * 64, 64, 128, 127, 191], 256, 256);
    assert.equal(square[128 * 256 + 64], 6);
    assert.equal(square[191 * 256 + 127], 6);
    assert.equal(square[127 * 256 + 64], -6);
    assert.equal(square[192 * 256 + 64], -6);
    assert.equal(square[128 * 256 + 128], -6);

    const landscape = maskToInput([0, 512 * 256, 0, 0, 511, 255], 512, 256);
    assert.ok(landscape.slice(0, 128 * 256).every((value) => value === 6));
    assert.ok(landscape.slice(128 * 256).every((value) => value === -6));
    const portrait = maskToInput([0, 256 * 512, 0, 0, 255, 511], 256, 512);
    for (let row = 0; row < 256; row++) {
        assert.equal(portrait[row * 256 + 127], 6);
        assert.equal(portrait[row * 256 + 128], -6);
    }
});

test('holes, fractional boundaries and ROI translation are preserved', () => {
    const hole = maskToInput([0, 1, 1, 2, 100, 100, 101, 101], 256, 256);
    assert.equal(hole[100 * 256 + 100], 6);
    assert.equal(hole[100 * 256 + 101], -6);
    const boundary = maskToInput([0, 1, 0, 0, 0, 0], 512, 512);
    assert.equal(boundary[0], -3); // one foreground pixel among four sampled pixels
    const cropped = maskToInput([0, 64 * 32, 100, 50, 163, 81], 500, 400, [100, 50, 164, 82]);
    assert.equal(cropped[0], 6);
    assert.equal(cropped[127 * 256 + 255], 6);
    assert.equal(cropped[128 * 256], -6);
});

async function makePlugin() {
    let plugin;
    const messages = [];
    class Worker {
        postMessage(message) {
            messages.push(message);
            const result = message.action === 'init' ? { action: 'init' } : {
                action: 'decode',
                payload: [{
                    points: new Uint8ClampedArray([1]), bounds: [0, 0, 0, 0],
                    mask_input: new Float32Array(256 * 256).fill(2),
                }],
            };
            queueMicrotask(() => this.onmessage({ data: result }));
        }
    }
    loadTS(path.join(sourceDirectory, 'index.tsx'), {
        'lru-cache': { LRUCache },
        'cvat-core-wrapper': { Source: { SEMI_AUTO: 'semi-auto' }, ShapeType: { MASK: 'mask' } },
        './inference.worker': { WorkerAction: { INIT: 'init', DECODE: 'decode' } },
        './mask-input': { default: maskToInput, __esModule: true },
    }, {
        Worker,
        window: {
            atob: (value) => Buffer.from(value, 'base64').toString('binary'),
            addEventListener: (_, callback) => callback(),
            cvatUI: {
                registerComponent: (builder) => builder({ core: {
                    plugins: { register: (value) => { plugin = value; } },
                    utils: { mask2Rle: () => [0, 1] },
                } }),
            },
        },
    });
    await plugin.cvat.jobs.get.leave(plugin, [{
        id: 1, taskId: 1, startFrame: 0, stopFrame: 5,
        frames: { get: async () => ({ width: 256, height: 256 }) },
    }], { jobID: 1 });
    return {
        infer: async (args) => {
            const model = { id: plugin.data.modelID };
            const cached = await plugin.cvat.lambda.call.enter(plugin, 1, model, args);
            const result = cached ? null : {
                model_type: 'vit_b', blob: Buffer.from(new Float32Array(256 * 64 * 64).buffer).toString('base64'),
            };
            await plugin.cvat.lambda.call.leave(plugin, result, 1, model, args);
            return messages.at(-1).payload.maskInput;
        },
    };
}

test('initial mask, iterative logits, prompt removal and object/session isolation', async () => {
    const { infer } = await makePlugin();
    const args = {
        frame: 0, pos_points: [[80, 80]], neg_points: [], obj_bbox: [], interaction_id: 'object-1',
        initial_mask: [0, 64 * 64, 64, 64, 127, 127],
    };
    const initial = await infer(args);
    assert.equal(initial[80 * 256 + 80], 6);
    assert.equal(initial[0], -6);
    const next = await infer({ ...args, neg_points: [[20, 20]] });
    assert.ok(next.every((value) => value === 2));
    assert.deepEqual(await infer(args), initial); // removing a point starts from the original annotation

    const another = await infer({
        ...args, interaction_id: 'object-2', neg_points: [[20, 20]],
        initial_mask: [0, 32 * 32, 160, 160, 191, 191],
    });
    assert.equal(another[80 * 256 + 80], -6);
    assert.equal(another[180 * 256 + 180], 6);
    assert.equal(await infer({ ...args, interaction_id: 'new-object', initial_mask: undefined }), null);
    assert.equal(await infer({ ...args, frame: 1, initial_mask: undefined }), null);
});

function makeControl(selected = true) {
    const filename = path.resolve(sourceDirectory,
        '../../../../src/components/annotation-page/standard-workspace/controls-side-bar/tools-control.tsx');
    const React = require('react');
    const placeholder = () => null;
    placeholder.Option = placeholder;
    const imports = Object.fromEntries(ts.preProcessFile(fs.readFileSync(filename, 'utf8')).importedFiles.map(
        ({ fileName }) => [fileName, {
            __esModule: true, default: placeholder, Row: placeholder, Col: placeholder,
            QuestionCircleOutlined: placeholder,
        }],
    ));
    const created = [];
    const updated = [];
    const calls = [];
    const canvasCalls = [];
    let registeredShortcuts;
    const core = {
        plugins: { register: () => {} },
        enums: { Source: { SEMI_AUTO: 'semi-auto' } },
        classes: { ObjectState: class { constructor(data) { Object.assign(this, data); } } },
        lambda: { call: async (...args) => { calls.push(args); return { shapes: [] }; } },
    };
    Object.assign(imports, {
        react: React,
        'react-redux': { connect: () => (component) => component },
        lodash: require('lodash'),
        'cvat-core-wrapper': {
            getCore: () => core, ShapeType: { MASK: 'mask', POLYGON: 'polygon' },
            ObjectType: { SHAPE: 'shape' }, DimensionType: { DIMENSION_2D: '2d' },
        },
        'cvat-canvas-wrapper': {
            convertShapesForInteractor: (shapes, shapeType, type) => shapes
                .filter((shape) => shape.shapeType === shapeType && shape.type === type).map((shape) => shape.points),
        },
        'antd/lib/message': { loading: () => () => {} },
        'antd/lib/notification': { error: ({ description }) => { throw Error(JSON.stringify(description)); } },
        'actions/shortcuts-actions': { registerComponentShortcuts: (value) => { registeredShortcuts = value; } },
        'utils/enums': { ShortcutScope: { STANDARD_WORKSPACE_CONTROLS: 'controls' } },
        'utils/component-subkeymap': { subKeyMap: (shortcuts, keyMap) => Object.fromEntries(
            Object.keys(shortcuts).map((key) => [key, keyMap[key]]),
        ) },
        './handle-popover-visibility': { __esModule: true, default: () => placeholder },
    });
    const { ToolsControlComponent } = loadTS(filename, imports, {
        localStorage: { getItem: () => null },
        window: {
            addEventListener: () => {}, removeEventListener: () => {},
            document: { getElementById: () => null },
        },
    });
    const target = {
        clientID: 42, serverID: 99, shapeType: 'mask', objectType: 'shape', frame: 0,
        points: [0, 4096, 64, 64, 127, 127], label: { id: 7 }, attributes: { 8: 'checked' },
        group: { id: 3 }, occluded: true, zOrder: 5, lock: false, hidden: false,
    };
    const props = {
        states: [target], selectedStatesID: [], activatedStateID: selected ? 42 : null,
        labels: [{ id: 1 }, target.label], activeLabelID: 1, isActivated: false, frame: 0,
        interactors: [{ id: 'pth-facebookresearch-sam-vit-h', version: 2, params: { canvas: {} } }],
        trackers: [], detectors: [], interactorExtras: [], jobInstance: { dimension: '2d', id: 1, taskId: 1 },
        keyMap: registeredShortcuts, normalizedKeyMap: { START_INTERACTION_STANDARD_CONTROLS: '[S]' },
        frameData: { width: 256, height: 256 }, toolsBlockerState: {}, defaultApproxPolyAccuracy: 5,
        createAnnotations: (states) => created.push(...states),
        updateAnnotations: async (states) => updated.push(...states),
        canvasInstance: {
            cancel: () => control.cancelListener(),
            interact: (data) => canvasCalls.push(data),
        },
        onInteractionStart: (_, activeLabelID) => {
            const prevProps = control.props;
            const prevState = control.state;
            control.props = { ...props, isActivated: true, activatedStateID: null, activeLabelID };
            control.componentDidUpdate(prevProps, prevState);
        },
    };
    const control = new ToolsControlComponent(props);
    control.setState = (state) => { control.state = { ...control.state, ...state }; };
    control.initializeOpenCV = async () => {};
    control.drawIntermediateShapesOnCanvas = () => {};
    const findButton = (node) => {
        if (!node || !node.props) return null;
        if (node.props.className === 'cvat-tools-interact-button') return node;
        return React.Children.toArray(node.props.children).map(findButton).find(Boolean);
    };
    return {
        control, target, created, updated, calls, canvasCalls, core, registeredShortcuts,
        button: () => findButton(control.renderInteractorBlock()),
        shortcut: (event) => control.shortcutHandlers.START_INTERACTION_STANDARD_CONTROLS(event),
    };
}

test('starting refinement captures the selected mask before activation is cleared; Done updates that object', async () => {
    const { control, target, created, updated, calls, canvasCalls, button } = makeControl();
    const metadata = { ...target };
    control.state.interactorRegionOfInterest = [0, 0, 32, 32];
    control.state.convertMasksToPolygons = true;
    button().props.onClick();
    assert.equal(canvasCalls[0].command, 'draw_points');
    assert.equal(canvasCalls[0].settings.regionOfInterest, undefined);
    assert.equal(control.props.activatedStateID, null);
    control.onInteraction({ detail: { shapes: [{ shapeType: 'points', type: 'positive', points: [80, 80] }] } });
    await new Promise(setImmediate);
    assert.deepEqual(Array.from(calls[0][2].initial_mask), target.points);
    assert.equal(calls[0][2].roi, undefined);
    const refined = [0, 2500, 70, 70, 119, 119];
    control.interaction.latestResponse = [{ rle: Int32Array.from(refined) }];
    await control.interactionListener({ detail: { shapes: [], finished: true } });
    assert.equal(created.length, 0);
    assert.equal(updated[0], target);
    assert.deepEqual({ ...target, points: metadata.points }, metadata);
    assert.deepEqual(Array.from(target.points), refined);
});

test('canceling with inference in flight discards the response and leaves the annotation intact', async () => {
    const { control, target, updated, created, core, button } = makeControl();
    const original = [...target.points];
    let complete;
    core.lambda.call = () => new Promise((resolve) => { complete = resolve; });
    button().props.onClick();
    control.onInteraction({ detail: { shapes: [{ shapeType: 'points', type: 'positive', points: [80, 80] }] } });
    await new Promise(setImmediate);
    await control.cancelListener();
    complete({ shapes: [{ type: 'mask', points: [0, 1, 0, 0, 0, 0], attributes: [] }] });
    await new Promise(setImmediate);
    assert.deepEqual(target.points, original);
    assert.equal(updated.length + created.length, 0);
    assert.equal(control.interaction.latestResponse.length, 0);
});

test('locked masks cannot start refinement; unselected interactions still create new objects', async () => {
    const locked = makeControl();
    locked.target.lock = true;
    assert.equal(locked.button().props.disabled, true);
    const { control, created, updated, button } = makeControl(false);
    button().props.onClick();
    control.interaction.latestResponse = [{ rle: Int32Array.from([0, 4096, 64, 64, 127, 127]) }];
    await control.interactionListener({ detail: { shapes: [], finished: true } });
    assert.equal(created.length, 1);
    assert.equal(updated.length, 0);
    assert.equal(created[0].shapeType, 'mask');
});

test('Interact shortcut captures a mask selected in Select Objects without opening AI Tools', async () => {
    const { control, target, calls, canvasCalls, shortcut } = makeControl();
    control.props.selectedStatesID = [target.clientID];
    control.props.activatedStateID = null;
    const hotkeys = require('react').Children.toArray(control.render().props.children)
        .find((node) => node.props.handlers?.START_INTERACTION_STANDARD_CONTROLS);
    assert.ok(hotkeys);
    assert.deepEqual(Array.from(hotkeys.props.keyMap.START_INTERACTION_STANDARD_CONTROLS.sequences), ['s']);
    hotkeys.props.handlers.START_INTERACTION_STANDARD_CONTROLS();
    control.onInteraction({ detail: { shapes: [{ shapeType: 'points', type: 'positive', points: [80, 80] }] } });
    await new Promise(setImmediate);
    assert.deepEqual(Array.from(calls[0][2].initial_mask), target.points);
    assert.equal(control.interaction.refinementTarget.clientID, target.clientID);
    const count = canvasCalls.length;
    shortcut(); // pressing again must not discard the active refinement
    assert.equal(canvasCalls.length, count);
});

test('Interact shortcut honors button availability and configured shortcuts', () => {
    for (const disable of [
        ({ target }) => { target.lock = true; },
        ({ target }) => { target.hidden = true; },
        ({ target }) => { target.isGroundTruth = true; },
        ({ control }) => { control.state.fetching = true; },
        ({ control }) => { control.props.frameData.deleted = true; },
        ({ control }) => { control.props.labels = []; },
        ({ control }) => { control.state.activeInteractor = null; },
        ({ control }) => { control.state.activeInteractor.version = 1; },
    ]) {
        const fixture = makeControl();
        disable(fixture);
        assert.equal(fixture.button().props.disabled, true);
        fixture.shortcut();
        assert.equal(fixture.canvasCalls.length, 0);
    }
    const { control, canvasCalls, shortcut } = makeControl(false);
    shortcut({ repeat: true, preventDefault: () => {} });
    assert.equal(canvasCalls.length, 0);
    const id = 'START_INTERACTION_STANDARD_CONTROLS';
    control.props.keyMap = { [id]: { ...control.props.keyMap[id], sequences: ['alt+i'] } };
    const hotkeys = require('react').Children.toArray(control.render().props.children)
        .find((node) => node.props.handlers?.[id]);
    assert.deepEqual(hotkeys.props.keyMap[id].sequences, ['alt+i']);
    hotkeys.props.handlers[id]();
    assert.equal(control.interaction.refinementTarget, null);
    assert.equal(canvasCalls.length, 1);
});

test('Select Objects shortcut toggles selection mode and respects disabled controls and remapping', () => {
    const React = require('react');
    const filename = path.resolve(sourceDirectory,
        '../../../../src/components/annotation-page/standard-workspace/controls-side-bar/select-control.tsx');
    const placeholder = () => null;
    let registered;
    const id = 'SWITCH_SELECT_MODE_STANDARD_CONTROLS';
    const shortcuts = { keyMap: {}, normalizedKeyMap: { [id]: '[Alt+S]' } };
    const { default: SelectControl } = loadTS(filename, {
        react: React,
        'react-redux': { useSelector: (selector) => selector({ shortcuts }) },
        '@ant-design/icons': placeholder,
        icons: { SelectIcon: placeholder },
        'components/common/cvat-tooltip': placeholder,
        reducers: { ActiveControl: { CURSOR: 'cursor', SELECT: 'select' } },
        'utils/mousetrap-react': placeholder,
        'actions/shortcuts-actions': { registerComponentShortcuts: (value) => { registered = value; } },
        'utils/enums': { ShortcutScope: { STANDARD_WORKSPACE_CONTROLS: 'controls' } },
        'utils/component-subkeymap': { subKeyMap: (_, keyMap) => keyMap },
    });
    assert.deepEqual(Array.from(registered[id].sequences), ['a']);
    shortcuts.keyMap[id] = { ...registered[id], sequences: ['alt+s'] };
    const calls = [];
    const props = {
        activeControl: 'cursor', disabled: false,
        canvasInstance: {
            cancel: () => calls.push('cancel'),
            selectObjects: ({ enabled }) => calls.push(enabled),
        },
        updateActiveControl: (control) => { props.activeControl = control; },
    };
    const render = () => React.Children.toArray(SelectControl.type(props).props.children);
    const [hotkeys, tooltip] = render();
    assert.deepEqual(hotkeys.props.keyMap[id].sequences, ['alt+s']);
    assert.equal(tooltip.props.title, 'Select objects [Alt+S]');
    hotkeys.props.handlers[id]();
    assert.equal(props.activeControl, 'select');
    render()[0].props.handlers[id]({ repeat: true, preventDefault: () => {} });
    assert.equal(props.activeControl, 'select');
    render()[0].props.handlers[id]();
    assert.equal(props.activeControl, 'cursor');
    assert.deepEqual(calls, ['cancel', true, false]);
    props.disabled = true;
    assert.equal(SelectControl.type(props).props.children, undefined);
});
