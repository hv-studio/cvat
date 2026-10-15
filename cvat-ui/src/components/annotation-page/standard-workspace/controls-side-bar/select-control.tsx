// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import { useSelector } from 'react-redux';
import Icon from '@ant-design/icons';
import { SelectIcon } from 'icons';

import { Canvas } from 'cvat-canvas-wrapper';
import CVATTooltip from 'components/common/cvat-tooltip';
import { ActiveControl, CombinedState } from 'reducers';
import GlobalHotKeys from 'utils/mousetrap-react';
import { registerComponentShortcuts } from 'actions/shortcuts-actions';
import { ShortcutScope } from 'utils/enums';
import { subKeyMap } from 'utils/component-subkeymap';

export interface Props {
    canvasInstance: Canvas;
    activeControl: ActiveControl;
    disabled: boolean;
    updateActiveControl(activeControl: ActiveControl): void;
}

const componentShortcuts = {
    SWITCH_SELECT_MODE_STANDARD_CONTROLS: {
        name: 'Select objects',
        description: 'Activate or deactivate object selection mode',
        sequences: ['a'],
        scope: ShortcutScope.STANDARD_WORKSPACE_CONTROLS,
    },
};

registerComponentShortcuts(componentShortcuts);

function SelectControl(props: Props): JSX.Element {
    const {
        canvasInstance, activeControl, disabled, updateActiveControl,
    } = props;
    const { keyMap, normalizedKeyMap } = useSelector((state: CombinedState) => state.shortcuts);
    const selecting = activeControl === ActiveControl.SELECT;

    const onClick = (): void => {
        if (disabled) return;
        if (selecting) {
            canvasInstance.selectObjects({ enabled: false });
            updateActiveControl(ActiveControl.CURSOR);
        } else {
            canvasInstance.cancel();
            canvasInstance.selectObjects({ enabled: true });
            updateActiveControl(ActiveControl.SELECT);
        }
    };

    const handlers = {
        SWITCH_SELECT_MODE_STANDARD_CONTROLS: (event?: KeyboardEvent): void => {
            event?.preventDefault();
            if (!event?.repeat) onClick();
        },
    };

    return disabled ? (
        <Icon component={SelectIcon} className='cvat-select-control cvat-disabled-canvas-control' />
    ) : (
        <>
            <GlobalHotKeys
                keyMap={subKeyMap(componentShortcuts, keyMap)}
                handlers={handlers}
            />
            <CVATTooltip
                title={`Select objects ${normalizedKeyMap.SWITCH_SELECT_MODE_STANDARD_CONTROLS}`}
                placement='right'
            >
                <Icon
                    component={SelectIcon}
                    className={selecting ?
                        'cvat-select-control cvat-active-canvas-control' :
                        'cvat-select-control'}
                    onClick={onClick}
                />
            </CVATTooltip>
        </>
    );
}

Object.assign(SelectControl, { displayName: 'SelectControl' });
export default React.memo(SelectControl);
