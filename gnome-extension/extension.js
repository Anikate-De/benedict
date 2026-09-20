import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const POLL_MS = 1000;
const STALE_S = 300;
const PULSE_MS = 550;
const CARET_MS = 500;
const TRANSCRIPT_LIMIT = 72;
const DEFAULT_MARGIN = 48;
const DOCK_CLEARANCE = 64;

export default class BenedictExtension extends Extension {
    enable() {
        const runtime = GLib.get_user_runtime_dir();
        this._focusPath = GLib.build_filenamev([runtime, 'benedict-focus']);
        this._statePath = GLib.build_filenamev([runtime, 'benedict-state.json']);
        this._position = 'bottom-center';
        this._margin = DEFAULT_MARGIN;
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
        this._stopPulse();
        this._stopCaret();
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
            vertical: true,
            reactive: false,
            track_hover: false,
            visible: false,
        });

        const row1 = new St.BoxLayout({
            style_class: 'benedict-row',
            x_expand: true,
        });
        this._dot = new St.Widget({
            style_class: 'benedict-dot',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._label = new St.Label({
            style_class: 'benedict-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._mic = new St.Label({
            style_class: 'benedict-mic',
            y_align: Clutter.ActorAlign.CENTER,
        });
        row1.add_child(this._dot);
        row1.add_child(this._label);
        row1.add_child(new St.Widget({x_expand: true}));
        row1.add_child(this._mic);

        this._row2 = new St.BoxLayout({
            style_class: 'benedict-transcript-row',
            visible: false,
        });
        this._transcript = new St.Label({
            style_class: 'benedict-transcript',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._caret = new St.Widget({
            style_class: 'benedict-caret',
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });
        this._row2.add_child(this._transcript);
        this._row2.add_child(this._caret);

        this._pill.add_child(row1);
        this._pill.add_child(this._row2);
        Main.uiGroup.add_child(this._pill);
    }

    _format(text) {
        if (!text)
            return '';
        return text.length > TRANSCRIPT_LIMIT ? `…${text.slice(-TRANSCRIPT_LIMIT)}` : text;
    }

    _show(text, detail, styleClass) {
        this._label.set_text(text);
        this._mic.set_text(detail.mic || '');
        this._mic.visible = Boolean(detail.mic);
        const transcript = this._format(detail.transcript);
        this._transcript.set_text(transcript);
        this._row2.visible = Boolean(transcript);
        this._caret.visible = Boolean(detail.caret && transcript);
        this._pill.set_style_class_name(`benedict-pill ${styleClass}`);
        this._pill.show();
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._reposition();
            return GLib.SOURCE_REMOVE;
        });
    }

    _reposition() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || !this._pill)
            return;
        const width = this._pill.get_preferred_width(-1)[1];
        const height = this._pill.get_preferred_height(-1)[1];
        const margin = this._margin;
        const bottomGap = margin + DOCK_CLEARANCE;
        const topMin = monitor.y + (Main.panel && Main.panel.height ? Main.panel.height + 8 : margin);
        let x = monitor.x + Math.floor((monitor.width - width) / 2);
        let y = monitor.y + monitor.height - height - bottomGap;
        switch (this._position) {
        case 'bottom-right':
            x = monitor.x + monitor.width - width - margin;
            break;
        case 'top-center':
            y = Math.max(monitor.y + margin, topMin);
            break;
        case 'top-right':
            x = monitor.x + monitor.width - width - margin;
            y = Math.max(monitor.y + margin, topMin);
            break;
        default:
            break;
        }
        x = Math.max(monitor.x + margin, x);
        y = Math.max(monitor.y + margin, y);
        this._pill.set_position(x, y);
    }

    _startPulse() {
        if (this._pulseId)
            return;
        this._pulseOn = true;
        this._pulseId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PULSE_MS, () => {
            this._pulseOn = !this._pulseOn;
            this._dot.opacity = this._pulseOn ? 255 : 90;
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopPulse() {
        if (this._pulseId) {
            GLib.source_remove(this._pulseId);
            this._pulseId = 0;
        }
        if (this._dot)
            this._dot.opacity = 255;
    }

    _setPulse(enabled) {
        if (enabled)
            this._startPulse();
        else
            this._stopPulse();
    }

    _setCaret(enabled) {
        if (enabled && !this._caretId) {
            this._caretOn = true;
            this._caretId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, CARET_MS, () => {
                this._caretOn = !this._caretOn;
                this._caret.opacity = this._caretOn ? 255 : 40;
                return GLib.SOURCE_CONTINUE;
            });
        } else if (!enabled) {
            this._stopCaret();
        }
    }

    _stopCaret() {
        if (this._caretId) {
            GLib.source_remove(this._caretId);
            this._caretId = 0;
        }
        if (this._caret)
            this._caret.opacity = 255;
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
            this._setCaret(false);
            return;
        }
        if (data.ui && data.ui.pill === false) {
            this._pill.hide();
            this._setPulse(false);
            this._setCaret(false);
            return;
        }
        if (data.ui && data.ui.position)
            this._position = data.ui.position;
        if (data.ui && typeof data.ui.margin === 'number')
            this._margin = Math.max(0, Math.min(400, data.ui.margin));

        let text;
        let styleClass;
        let mic = '';
        let transcript = '';
        let caret = false;
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
            text = 'Listening';
            styleClass = 'benedict-recording';
            mic = data.mic || '';
            transcript = data.transcript || '';
            caret = true;
            break;
        case 'finalizing':
            text = 'Transcribing…';
            styleClass = 'benedict-warming';
            mic = data.mic || '';
            transcript = data.transcript || '';
            break;
        case 'inserting':
            text = 'Inserting…';
            styleClass = 'benedict-warming';
            transcript = data.transcript || '';
            break;
        case 'inserted': {
            const words = data.words;
            text = words != null
                ? `Pasted ${words} word${words === 1 ? '' : 's'}`
                : 'Pasted';
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
            this._setCaret(false);
            return;
        }

        this._setPulse(data.state === 'recording');
        this._setCaret(data.state === 'recording');
        this._show(text, {mic, transcript, caret}, styleClass);
    }
}
