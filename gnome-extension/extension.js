import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const POLL_MS = 1000;
const STALE_S = 120;
const PULSE_MS = 500;

export default class BenedictExtension extends Extension {
    enable() {
        const runtime = GLib.get_user_runtime_dir();
        this._focusPath = GLib.build_filenamev([runtime, 'benedict-focus']);
        this._statePath = GLib.build_filenamev([runtime, 'benedict-state.json']);
        this._focusHandler = global.display.connect('notify::focus-window', () => this._writeFocus());
        this._writeFocus();

        this._buildPill();
        this._monitor = Gio.File.new_for_path(runtime).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, null);
        this._monitor.connect('changed', (monitor, file) => {
            if (file && file.get_basename() === 'benedict-state.json')
                this._update();
        });
        this._pollId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, POLL_MS, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => {
            if (this._pill.visible)
                this._reposition();
        });
        this._update();
    }

    disable() {
        if (this._focusHandler) {
            global.display.disconnect(this._focusHandler);
            this._focusHandler = 0;
        }
        if (this._monitorsId) {
            Main.layoutManager.disconnect(this._monitorsId);
            this._monitorsId = 0;
        }
        if (this._monitor) {
            this._monitor.cancel();
            this._monitor = null;
        }
        if (this._pollId) {
            GLib.source_remove(this._pollId);
            this._pollId = 0;
        }
        this._setPulse(false);
        if (this._pill) {
            this._pill.destroy();
            this._pill = null;
        }
    }

    _writeFocus() {
        const window = global.display.focus_window;
        const wmClass = window ? window.get_wm_class() || '' : '';
        try {
            Gio.File.new_for_path(this._focusPath).replace_contents(
                wmClass, null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        } catch (error) {
            logError(error);
        }
    }

    _buildPill() {
        this._pill = new St.BoxLayout({
            style_class: 'benedict-pill',
            reactive: false,
            track_hover: false,
            visible: false,
        });
        this._dot = new St.Widget({
            style_class: 'benedict-dot',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._label = new St.Label({
            style_class: 'benedict-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._transcript = new St.Label({
            style_class: 'benedict-transcript',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._pill.add_child(this._dot);
        this._pill.add_child(this._label);
        this._pill.add_child(this._transcript);
        Main.uiGroup.add_child(this._pill);
    }

    _show(text, transcript, styleClass) {
        this._label.set_text(text);
        this._transcript.set_text(transcript || '');
        this._transcript.visible = Boolean(transcript);
        this._pill.set_style_class_name(`benedict-pill ${styleClass}`);
        this._pill.show();
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._reposition();
            return GLib.SOURCE_REMOVE;
        });
    }

    _reposition() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const width = this._pill.get_preferred_width()[1];
        const height = this._pill.get_preferred_height()[1];
        const x = monitor.x + Math.floor((monitor.width - width) / 2);
        const y = monitor.y + monitor.height - height - 110;
        this._pill.set_position(x, y);
    }

    _setPulse(enabled) {
        if (enabled && !this._pulseId) {
            this._pulseOn = true;
            this._pulseId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PULSE_MS, () => {
                this._pulseOn = !this._pulseOn;
                this._dot.opacity = this._pulseOn ? 255 : 90;
                return GLib.SOURCE_CONTINUE;
            });
        } else if (!enabled && this._pulseId) {
            GLib.source_remove(this._pulseId);
            this._pulseId = 0;
            this._dot.opacity = 255;
        }
    }

    _update() {
        let data = null;
        try {
            const [ok, contents] = GLib.file_get_contents(this._statePath);
            if (ok)
                data = JSON.parse(new TextDecoder().decode(contents));
        } catch (error) {
            data = null;
        }
        if (!data || !data.state || Date.now() / 1000 - data.ts > STALE_S) {
            this._pill.hide();
            this._setPulse(false);
            return;
        }

        let text;
        let styleClass;
        switch (data.state) {
        case 'ready':
            text = `Ready — hold ${data.hint || 'the hotkey'}`;
            styleClass = 'benedict-warming';
            break;
        case 'starting':
            text = 'Starting dictation…';
            styleClass = 'benedict-warming';
            break;
        case 'recording':
            text = data.mic ? `Listening · ${data.mic}` : 'Listening';
            styleClass = 'benedict-recording';
            break;
        case 'finalizing':
            text = 'Transcribing…';
            styleClass = 'benedict-warming';
            break;
        case 'inserting':
            text = 'Inserting…';
            styleClass = 'benedict-warming';
            break;
        case 'inserted': {
            const words = data.words;
            text = words != null
                ? `Inserted ${words} word${words === 1 ? '' : 's'}`
                : 'Inserted';
            styleClass = 'benedict-done';
            break;
        }
        case 'error':
            text = data.message || 'Dictation failed';
            styleClass = 'benedict-error';
            break;
        default:
            this._pill.hide();
            this._setPulse(false);
            return;
        }

        const recording = data.state === 'recording';
        this._setPulse(recording);
        this._show(text, recording ? data.transcript : '', styleClass);
    }
}
